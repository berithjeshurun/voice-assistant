import { ButtonHTMLAttributes } from "react";
import "./SpecularButton.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost";
};

/** React Bits–inspired glass/specular button. */
export default function SpecularButton({
  variant = "primary",
  className = "",
  children,
  ...rest
}: Props) {
  return (
    <button
      type="button"
      className={`rb-specular rb-specular--${variant} ${className}`.trim()}
      {...rest}
    >
      <span className="rb-specular__shine" aria-hidden />
      <span className="rb-specular__label">{children}</span>
    </button>
  );
}
