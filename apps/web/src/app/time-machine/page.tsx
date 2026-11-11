import type { Metadata } from "next";
import { TimeMachine } from "@/components/TimeMachine";
import { shareImageUrl } from "@/lib/api/client";

type Params = Promise<{ [k: string]: string | string[] | undefined }>;
const one = (v: string | string[] | undefined, d: string) => (Array.isArray(v) ? v[0] : v) ?? d;

export async function generateMetadata({ searchParams }: { searchParams: Params }): Promise<Metadata> {
  const sp = await searchParams;
  const product = one(sp.product, "p_mug");
  const origin = one(sp.origin, "GB");
  const destination = one(sp.destination, "US");
  const date = typeof sp.date === "string" ? sp.date : undefined;
  const img = shareImageUrl({ product, origin, destination, date });
  const title = "Tariff Time Machine: what a buyer really paid, month by month";
  return {
    title: "Tariff Time Machine",
    description: "Pick a product, an origin and a destination, then drag through time to see the price a buyer paid on any date. Numbers and sources only.",
    openGraph: { title, type: "website", images: [{ url: img, width: 1200, height: 630 }] },
    twitter: { card: "summary_large_image", title, images: [img] },
  };
}

export default async function Page({ searchParams }: { searchParams: Params }) {
  const sp = await searchParams;
  return (
    <TimeMachine
      initial={{
        product: one(sp.product, "p_mug"),
        origin: one(sp.origin, "GB"),
        destination: one(sp.destination, "US") as "US" | "EU" | "GB",
        date: typeof sp.date === "string" ? sp.date : null,
      }}
    />
  );
}
