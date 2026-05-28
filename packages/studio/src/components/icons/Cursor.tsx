import { forwardRef, useId, type SVGProps } from "react";

export const Cursor = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
  function Cursor(props, ref) {
    const uid = useId();
    const gradTop = `cursor-top-${uid}`;
    const gradLeft = `cursor-left-${uid}`;
    const gradRight = `cursor-right-${uid}`;
    return (
      <svg
        ref={ref}
        xmlns="http://www.w3.org/2000/svg"
        width="24"
        height="24"
        viewBox="0 0 24 24"
        role="img"
        aria-label="Cursor"
        {...props}
      >
        <defs>
          <linearGradient id={gradTop} x1="12" y1="0" x2="12" y2="24" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#a3a3a3" />
            <stop offset="1" stopColor="#1a1a1a" />
          </linearGradient>
          <linearGradient id={gradLeft} x1="0" y1="12" x2="24" y2="12" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#000000" />
            <stop offset="1" stopColor="#404040" />
          </linearGradient>
          <linearGradient id={gradRight} x1="24" y1="12" x2="0" y2="12" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#262626" />
            <stop offset="1" stopColor="#000000" />
          </linearGradient>
        </defs>
        <path
          fill={`url(#${gradTop})`}
          d="M11.503.131 1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.61-5.55a.84.84 0 0 0 .42-.724V6.404a.84.84 0 0 0-.42-.726L12.497.131a1.01 1.01 0 0 0-.996 0Z"
        />
        <path
          fill={`url(#${gradLeft})`}
          d="M11.999 12.336v10.523c0 .124.167.167.229.06L21.504 6.853c.132-.228-.032-.515-.295-.515H2.657c-.124 0-.169.167-.06.229l9.108 5.258a.59.59 0 0 1 .294.51Z"
          opacity="0.85"
        />
        <path
          fill={`url(#${gradRight})`}
          d="M22 6.403v11.187c0 .118-.029.232-.084.332L12 12.339 22 6.403Z"
          opacity="0.7"
        />
      </svg>
    );
  },
);
