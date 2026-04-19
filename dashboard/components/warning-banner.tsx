import { AlertTriangle } from "lucide-react";

export function WarningBanner() {
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <div>
        <span className="font-medium">Facebook ToS notice.</span>{" "}
        Automating posts violates Facebook&apos;s Terms. For personal use with
        reasonable delays the risk is low but not zero. Do not use this with
        your primary account.
      </div>
    </div>
  );
}
