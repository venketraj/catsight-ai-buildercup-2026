/**
 * The CatSight mark: a lens (sight) with a storm swirl inside it (cat, as in
 * catastrophe). Drawn in the brand teal; the swirl takes the panel colour so
 * it reads in both themes. The same drawing is public/favicon.svg.
 */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="logo">
      <circle cx="16" cy="16" r="14" fill="var(--ours)" />
      <path
        d="M16 8.5a7.5 7.5 0 1 1-7.4 8.7M16 12a4 4 0 1 1-3.9 4.8M16 15.4a.9.9 0 1 1-.9.9"
        fill="none"
        stroke="var(--panel)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}
