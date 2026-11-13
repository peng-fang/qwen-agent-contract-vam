interface BrandLogoProps {
  size?: number
  className?: string
}

export function BrandLogo({ size = 96, className = '' }: BrandLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="签之前 logo"
    >
      <defs>
        <linearGradient id="brandGradient" x1="8" y1="4" x2="56" y2="60" gradientUnits="userSpaceOnUse">
          <stop stopColor="#4F46E5" />
          <stop offset="0.55" stopColor="#2563EB" />
          <stop offset="1" stopColor="#0EA5E9" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#brandGradient)" />
      <path
        d="M20 14.5h16.5L44 22v27.5H20V14.5Z"
        fill="white"
        fillOpacity="0.96"
      />
      <path d="M36.5 14.5V22H44" stroke="#BFDBFE" strokeWidth="2.2" strokeLinejoin="round" />
      <path
        d="M26 36.5l4.2 4.2L39 30.5"
        stroke="#2563EB"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M26 44h12" stroke="#93C5FD" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}
