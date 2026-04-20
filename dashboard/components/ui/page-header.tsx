import Link from "next/link";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  icon: Icon,
  actions,
  learnMoreHref,
  className,
}: {
  title: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }>;
  actions?: React.ReactNode;
  learnMoreHref?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 md:flex-row md:items-start md:justify-between",
        className,
      )}
    >
      <div className="max-w-3xl">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="h-6 w-6 text-muted-foreground" />}
          <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        </div>
        {description && (
          <p className="mt-1 text-muted-foreground">
            {description}
            {learnMoreHref && (
              <>
                {" "}
                <Link
                  href={learnMoreHref}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  Learn more
                </Link>
                .
              </>
            )}
          </p>
        )}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
