import { useParams } from "react-router-dom";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function PlaceholderSection({ title }: { title: string }) {
  const { projectId } = useParams();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          {title} for project {projectId} is not yet implemented.
        </p>
      </CardContent>
    </Card>
  );
}
