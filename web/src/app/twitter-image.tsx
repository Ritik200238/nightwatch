import { OG_SIZE, ogImage } from "@/lib/og";

export const alt = "Nightwatch: stress-test a tokenized US stock trade before you place it";
export const size = OG_SIZE;
export const contentType = "image/png";

export default function Image() {
  return ogImage(null);
}
