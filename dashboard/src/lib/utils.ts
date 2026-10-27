import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
/** A stored number to `digits` decimals; a value the writer did not store reads "-". */
export function fixed(value: number | null, digits: number): string {
  return value === null ? "-" : value.toFixed(digits)
}

/** A snake_case code as words ("shadow_only" -> "shadow only"). */
export function spaced(code: string): string {
  return code.replaceAll("_", " ")
}
