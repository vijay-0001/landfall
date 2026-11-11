import type { Metadata } from "next";
import { Suspense } from "react";
import { Shop } from "@/components/Shop";

export const metadata: Metadata = { title: "Shop" };

export default function Page() {
  return <Suspense fallback={null}><Shop /></Suspense>;
}
