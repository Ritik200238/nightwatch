import { OG_SIZE, ogImage } from "@/lib/og";
import { shareFacts } from "@/lib/site-api";

export const alt = "A stored Nightwatch stress test";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return ogImage(await shareFacts(id));
}
