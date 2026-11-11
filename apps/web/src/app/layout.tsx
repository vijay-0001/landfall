import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "Landfall: duties included at PayPal checkout", template: "%s · Landfall" },
  description: "Your parcel lands. Nothing to pay at the door. The AI recommends, the seller accepts, the buyer pays one clear price.",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#14213D" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
