import type { Metadata } from "next";
import { Suspense } from "react";
import { Checkout } from "@/components/Checkout";

export const metadata: Metadata = { title: "Checkout" };

export default function Page() {
  return <Suspense fallback={null}><Checkout /></Suspense>;
}
