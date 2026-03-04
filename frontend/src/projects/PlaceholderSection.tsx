import { Construction } from "lucide-react";

export default function PlaceholderSection({ title }: { title: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-16">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <Construction className="h-6 w-6 text-muted-foreground" />
      </div>
      <p className="text-lg font-medium text-foreground">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">
        This section is not yet implemented.
      </p>
    </div>
  );
}
