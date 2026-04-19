"use client";

import { useEffect, useState } from "react";
import { getAuthStatus, login, type AuthStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const s = await getAuthStatus();
      setStatus(s);
    } catch {
      // If /api/auth/status itself is gated, the backend is misconfigured —
      // but in that case there's nothing useful we can render.
      setStatus({ auth_required: true, authenticated: false });
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await login(pin);
      setPin("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  if (status === null) {
    return null;
  }
  if (!status.auth_required || status.authenticated) {
    return <>{children}</>;
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Dashboard locked</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Enter the PIN from your <code>.env</code> (DASHBOARD_PIN) to continue.
          </p>
          <Input
            type="password"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            autoFocus
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <Button onClick={submit} disabled={busy || !pin}>
            {busy ? "Signing in…" : "Unlock"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
