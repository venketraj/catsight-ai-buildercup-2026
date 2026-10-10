<#
    CatSight - GCP access checks (BUILD_PLAN decision #2).

    Run this ONCE after `gcloud auth application-default login`. It answers
    every question that cannot be answered offline, and prints a PASS/FAIL per
    item so the gaps are explicit rather than discovered mid-build.

    Read-only by default. Nothing here creates, deletes or bills anything
    except section 9, which sends ONE tiny request per model (a few hundred
    tokens, well under a cent) because model availability cannot be
    established any other way.

    Usage:
        powershell -ExecutionPolicy Bypass -File scripts/check_access.ps1
        powershell -ExecutionPolicy Bypass -File scripts/check_access.ps1 -SkipModelCalls

    Windows PowerShell 5.1 compatible: no &&, no ternary, no ?? operators.
#>

param(
    [string] $ProjectId = "techno-crackers-catsight",
    [string] $Location  = "global",
    [switch] $SkipModelCalls
)

$ErrorActionPreference = "Continue"
$script:Pass  = 0
$script:Fail  = 0
$script:Warn  = 0
$script:Notes = New-Object System.Collections.ArrayList

function Write-Result {
    param([string] $Status, [string] $Name, [string] $Detail)
    if ($Status -eq "PASS") {
        $colour = "Green"
        $script:Pass++
    } elseif ($Status -eq "WARN") {
        $colour = "Yellow"
        $script:Warn++
    } else {
        $colour = "Red"
        $script:Fail++
    }
    Write-Host ("  [{0}] {1}" -f $Status.PadRight(4), $Name) -ForegroundColor $colour
    if ($Detail) {
        Write-Host ("         {0}" -f $Detail) -ForegroundColor DarkGray
    }
    if ($Status -ne "PASS") {
        [void] $script:Notes.Add(("{0}: {1} - {2}" -f $Status, $Name, $Detail))
    }
}

function Invoke-GCloud {
    # Returns stdout as a trimmed string, or $null when the command failed.
    param([string[]] $GcloudArgs)
    $out = & gcloud @GcloudArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $text = ($out | Out-String).Trim()
    if ($text -eq "") { return $null }
    return $text
}

function Read-ErrorBody {
    # Vertex returns the useful part of a failure in the response body, not in
    # Exception.Message, so a bare message would hide the actual reason.
    param($ErrorRecord)
    $msg = $ErrorRecord.Exception.Message
    if ($ErrorRecord.Exception.Response) {
        try {
            $stream = $ErrorRecord.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $body   = $reader.ReadToEnd()
            $reader.Close()
            if ($body) { $msg = $body }
        } catch {
            # keep the original message
        }
    }
    $msg = ($msg -replace "\s+", " ").Trim()
    if ($msg.Length -gt 400) { $msg = $msg.Substring(0, 400) + " ..." }
    return $msg
}

Write-Host ""
Write-Host "CatSight - GCP access checks" -ForegroundColor Cyan
Write-Host ("project: {0}   location: {1}" -f $ProjectId, $Location) -ForegroundColor Cyan
Write-Host ("=" * 70)

# -- 1. tooling -------------------------------------------------------------- #
Write-Host ""
Write-Host "1. Tooling"
$gcloudCmd = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloudCmd) {
    Write-Result "FAIL" "gcloud CLI on PATH" "Install it, then open a NEW terminal so PATH refreshes."
    Write-Host ""
    Write-Host "Cannot continue without gcloud." -ForegroundColor Red
    exit 1
}
$sdkVersion = Invoke-GCloud @("version", "--format=value(.""Google Cloud SDK"")")
Write-Result "PASS" "gcloud CLI on PATH" ("SDK " + $sdkVersion)

$firebaseCmd = Get-Command firebase -ErrorAction SilentlyContinue
if ($firebaseCmd) {
    Write-Result "PASS" "firebase CLI on PATH" (& firebase --version 2>$null)
} else {
    Write-Result "WARN" "firebase CLI on PATH" "Needed only at S8 (Hosting deploy): npm i -g firebase-tools"
}

# -- 2. identity ------------------------------------------------------------- #
Write-Host ""
Write-Host "2. Identity"
$account = Invoke-GCloud @("config", "get-value", "account")
if ($account -and $account -ne "(unset)") {
    Write-Result "PASS" "gcloud account" $account
} else {
    $account = $null
    Write-Result "FAIL" "gcloud account" "Run: gcloud auth login"
}

$adcToken = Invoke-GCloud @("auth", "application-default", "print-access-token")
if ($adcToken) {
    Write-Result "PASS" "application-default credentials" "ADC present - the Python SDK can authenticate"
} else {
    Write-Result "FAIL" "application-default credentials" "Run: gcloud auth application-default login"
}

# -- 3. project -------------------------------------------------------------- #
Write-Host ""
Write-Host "3. Project"
$projectNumber = Invoke-GCloud @("projects", "describe", $ProjectId, "--format=value(projectNumber)")
if ($projectNumber) {
    Write-Result "PASS" "project reachable" ("projectNumber " + $projectNumber)
} else {
    Write-Result "FAIL" "project reachable" ("Cannot describe " + $ProjectId + " - wrong ID, or this account has no access.")
}

$billing = Invoke-GCloud @("billing", "projects", "describe", $ProjectId, "--format=value(billingEnabled)")
if ($billing -eq "True") {
    Write-Result "PASS" "billing enabled" "Vertex AI requires a linked billing account"
} elseif ($billing -eq "False") {
    Write-Result "FAIL" "billing enabled" "NOT linked - Vertex AI will refuse every request."
} else {
    Write-Result "WARN" "billing enabled" "Could not read billing. Needs the Cloud Billing API plus billing.resourceAssociations.list; access may still be fine."
}

# -- 4. IAM ------------------------------------------------------------------ #
Write-Host ""
Write-Host "4. IAM"
if ($account -and $projectNumber) {
    $memberFilter = "bindings.members:user:" + $account
    $roles = Invoke-GCloud @("projects", "get-iam-policy", $ProjectId,
                             "--flatten=bindings[].members",
                             "--filter=$memberFilter",
                             "--format=value(bindings.role)")
    if ($roles) {
        $roleList = (($roles -split "\r?\n") | Where-Object { $_ }) -join ", "
        if ($roleList -match "roles/(owner|editor)") {
            Write-Result "PASS" "roles on project" $roleList
        } else {
            Write-Result "WARN" "roles on project" ($roleList + " - may be too narrow to create the Firestore DB, the bucket or the vector index.")
        }
    } else {
        Write-Result "WARN" "roles on project" "Could not read the IAM policy (needs resourcemanager.projects.getIamPolicy). Access may still work."
    }
} else {
    Write-Result "WARN" "roles on project" "Skipped - no account or no project access."
}

# -- 5. services ------------------------------------------------------------- #
Write-Host ""
Write-Host "5. Services"
$needed = @(
    @{ api = "aiplatform.googleapis.com";       why = "Gemini + embeddings (S3, S4)" },
    @{ api = "firestore.googleapis.com";        why = "portfolio + vector index (S3)" },
    @{ api = "storage.googleapis.com";          why = "wording PDFs (S3)" },
    @{ api = "run.googleapis.com";              why = "API deploy (S5)" },
    @{ api = "cloudbuild.googleapis.com";       why = "container build (S5)" },
    @{ api = "artifactregistry.googleapis.com"; why = "container registry (S5)" },
    @{ api = "secretmanager.googleapis.com";    why = "ADMIN_TOKEN (S5)" },
    @{ api = "firebasehosting.googleapis.com";  why = "frontend deploy (S8)" }
)
$enabledRaw = Invoke-GCloud @("services", "list", "--enabled", "--project=$ProjectId", "--format=value(config.name)")
if ($null -eq $enabledRaw) {
    Write-Result "FAIL" "read enabled services" "Cannot list services - fix the account and project above first."
} else {
    $enabled = @(($enabledRaw -split "\r?\n") | Where-Object { $_ })
    $missing = New-Object System.Collections.ArrayList
    foreach ($item in $needed) {
        if ($enabled -contains $item.api) {
            Write-Result "PASS" $item.api $item.why
        } else {
            Write-Result "FAIL" $item.api ("NOT enabled - " + $item.why)
            [void] $missing.Add($item.api)
        }
    }
    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Host "  Enable them in one call:" -ForegroundColor Yellow
        Write-Host ("    gcloud services enable {0} --project={1}" -f (($missing | ForEach-Object { $_ }) -join " "), $ProjectId) -ForegroundColor Yellow
    }
}

# -- 6. Firestore ------------------------------------------------------------ #
Write-Host ""
Write-Host "6. Firestore"
$dbType = Invoke-GCloud @("firestore", "databases", "describe", "--database=(default)", "--project=$ProjectId", "--format=value(type)")
if ($dbType) {
    $dbLocation = Invoke-GCloud @("firestore", "databases", "describe", "--database=(default)", "--project=$ProjectId", "--format=value(locationId)")
    if ($dbType -match "FIRESTORE_NATIVE") {
        Write-Result "PASS" "(default) database" ("Native mode, " + $dbLocation)
    } else {
        Write-Result "FAIL" "(default) database" ($dbType + " - vector search needs FIRESTORE_NATIVE, and the mode cannot be switched in place.")
    }
} else {
    Write-Result "FAIL" "(default) database" ("Does not exist. Create it: gcloud firestore databases create --location=us-central1 --project=" + $ProjectId)
}

# -- 7. Cloud Storage -------------------------------------------------------- #
Write-Host ""
Write-Host "7. Cloud Storage"
$bucket = $ProjectId + "-docs"
$bucketLocation = Invoke-GCloud @("storage", "buckets", "describe", ("gs://" + $bucket), "--project=$ProjectId", "--format=value(location)")
if ($bucketLocation) {
    Write-Result "PASS" ("gs://" + $bucket) $bucketLocation
} else {
    Write-Result "WARN" ("gs://" + $bucket) ("Not found. Create it: gcloud storage buckets create gs://" + $bucket + " --location=us-central1 --project=" + $ProjectId)
}

# -- 8. Vertex AI reachability ----------------------------------------------- #
Write-Host ""
Write-Host "8. Vertex AI reachability"
if (-not $adcToken) {
    Write-Result "WARN" "aiplatform endpoint" "Skipped - no ADC token."
} else {
    $listUrl = "https://aiplatform.googleapis.com/v1/projects/$ProjectId/locations/$Location/publishers/google/models"
    try {
        $null = Invoke-RestMethod -Method Get -Uri $listUrl -Headers @{ Authorization = ("Bearer " + $adcToken) } -TimeoutSec 30
        Write-Result "PASS" "aiplatform endpoint" ("reachable at location=" + $Location)
    } catch {
        Write-Result "WARN" "aiplatform endpoint" ("List call failed: " + (Read-ErrorBody $_) + " -- section 9 is the real test.")
    }
}

# -- 9. model resolution ----------------------------------------------------- #
Write-Host ""
Write-Host "9. Models (C-2) - the checks that cannot be stubbed"
$chatModels = @("gemini-3.5-flash-lite", "gemini-3.8-flash")
$embedModel = "gemini-embedding-001"

if ($SkipModelCalls) {
    Write-Result "WARN" "model calls" "Skipped by -SkipModelCalls."
} elseif (-not $adcToken) {
    Write-Result "WARN" "model calls" "Skipped - no ADC token."
} else {
    $headers = @{ Authorization = ("Bearer " + $adcToken); "Content-Type" = "application/json" }
    $base    = "https://aiplatform.googleapis.com/v1/projects/$ProjectId/locations/$Location/publishers/google/models/"

    foreach ($model in $chatModels) {
        $url  = $base + $model + ":generateContent"
        $body = @{
            contents = @(
                @{ role = "user"; parts = @(@{ text = "Reply with the single word: ok" }) }
            )
            generationConfig = @{ maxOutputTokens = 16; temperature = 0 }
        } | ConvertTo-Json -Depth 10 -Compress
        try {
            $null = Invoke-RestMethod -Method Post -Uri $url -Headers $headers -Body $body -TimeoutSec 60
            Write-Result "PASS" ("model " + $model) "resolves and responds"
        } catch {
            Write-Result "FAIL" ("model " + $model) (Read-ErrorBody $_)
        }
    }

    # Structured output. FR-INGEST-1 and every agent schema depend on it, so a
    # model that resolves but ignores response_schema is still a blocker.
    $schemaUrl  = $base + $chatModels[0] + ":generateContent"
    $schemaBody = @{
        contents = @(
            @{ role = "user"; parts = @(@{ text = "This layer attaches at 10 and has a limit of 20." }) }
        )
        generationConfig = @{
            responseMimeType = "application/json"
            responseSchema   = @{
                type       = "OBJECT"
                properties = @{
                    retention = @{ type = "NUMBER" }
                    limit     = @{ type = "NUMBER" }
                }
                required = @("retention", "limit")
            }
            maxOutputTokens = 64
            temperature     = 0
        }
    } | ConvertTo-Json -Depth 12 -Compress
    try {
        $schemaResp = Invoke-RestMethod -Method Post -Uri $schemaUrl -Headers $headers -Body $schemaBody -TimeoutSec 60
        $schemaText = ($schemaResp.candidates[0].content.parts[0].text -replace "\s+", " ").Trim()
        Write-Result "PASS" "response_schema honoured" ("returned " + $schemaText)
    } catch {
        Write-Result "FAIL" "response_schema honoured" (Read-ErrorBody $_)
    }

    # Embeddings. The dimension must be 768 or it will not match EMBED_DIM and
    # the Firestore vector index, which is fixed at index-creation time.
    $embedUrl  = $base + $embedModel + ":predict"
    $embedBody = @{
        instances  = @(
            @{ content = "loss occurrence means any one event"; task_type = "RETRIEVAL_DOCUMENT" }
        )
        parameters = @{ outputDimensionality = 768 }
    } | ConvertTo-Json -Depth 10 -Compress
    try {
        $embedResp = Invoke-RestMethod -Method Post -Uri $embedUrl -Headers $headers -Body $embedBody -TimeoutSec 60
        $dimension = @($embedResp.predictions[0].embeddings.values).Count
        if ($dimension -eq 768) {
            Write-Result "PASS" ("embeddings " + $embedModel) "768 dimensions, matches EMBED_DIM and the vector index"
        } else {
            Write-Result "FAIL" ("embeddings " + $embedModel) ("returned " + $dimension + " dimensions, expected 768")
        }
    } catch {
        Write-Result "FAIL" ("embeddings " + $embedModel) (Read-ErrorBody $_)
    }
}

# -- summary ----------------------------------------------------------------- #
Write-Host ""
Write-Host ("=" * 70)
Write-Host ("PASS {0}   WARN {1}   FAIL {2}" -f $script:Pass, $script:Warn, $script:Fail)
if ($script:Notes.Count -gt 0) {
    Write-Host ""
    Write-Host "Not green:" -ForegroundColor Yellow
    foreach ($note in $script:Notes) {
        Write-Host ("  - " + $note) -ForegroundColor Yellow
    }
}
Write-Host ""
if ($script:Fail -gt 0) {
    Write-Host "Paste this whole output back into the build session." -ForegroundColor Cyan
    exit 1
}
Write-Host "All hard checks green - S3's online half is unblocked." -ForegroundColor Green
exit 0
