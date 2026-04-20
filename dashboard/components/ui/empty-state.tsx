import Link from "next/link";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  cta,
  secondaryCta,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  cta?: { label: string; href?: string; onClick?: () => void };
  secondaryCta?: { label: string; href?: string; onClick?: () => void };
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center",
        className,
      )}
    >
      {Icon && (
        <div className="mb-3 rounded-full bg-muted p-3">
          <Icon className="h-6 w-6 text-muted-foreground" />
        </div>
      )}
      <h3 className="text-base font-medium">{title}</h3>
      {description && (
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          {description}
        </p>
      )}
      {(cta || secondaryCta) && (
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {cta && <CtaButton cta={cta} />}
          {secondaryCta && <CtaButton cta={secondaryCta} variant="outline" />}
        </div>
      )}
    </div>
  );
}

function CtaButton({
  cta,
  variant = "default",
}: {
  cta: { label: string; href?: string; onClick?: () => void };
  variant?: "default" | "outline";
}) {
  if (cta.href) {
    return (
      <Link href={cta.href}>
        <Button variant={variant}>{cta.label}</Button>
      </Link>
    );
  }
  return (
    <Button variant={variant} onClick={cta.onClick}>
      {cta.label}
    </Button>
  );
}
