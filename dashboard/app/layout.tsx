import type { Metadata } from "next";
import { AuthGate } from "@/components/auth-gate";
import { Sidebar } from "@/components/layout/sidebar";
import { StatusBar } from "@/components/layout/status-bar";
import { HelpDrawer } from "@/components/layout/help-drawer";
import "./globals.css";

export const metadata: Metadata = {
  title: "autoposter-AI",
  description: "Local self-hosted AI social poster",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans antialiased">
        <AuthGate>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 p-6 space-y-4">
              <StatusBar />
              {children}
            </main>
          </div>
          <HelpDrawer />
        </AuthGate>
      </body>
    </html>
  );
}
