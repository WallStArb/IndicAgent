import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
/** A snake_case code as words ("shadow_only" -> "shadow only"). */
export function spaced(code: string): string {
  return code.replaceAll("_", " ")
}
