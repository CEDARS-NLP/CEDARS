import { useOutletContext } from "react-router-dom";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ProjectDetail {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  created_at: string;
}

export default function ProjectOverview() {
  const { project } = useOutletContext<{ project: ProjectDetail }>();

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Project Overview</CardTitle>
          <CardDescription>
            {project?.description || "No description provided"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-sm font-medium text-muted-foreground">
                Project ID
              </dt>
              <dd className="mt-1 text-sm">{project?.id}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-muted-foreground">
                Created
              </dt>
              <dd className="mt-1 text-sm">
                {project?.created_at
                  ? new Date(project.created_at).toLocaleDateString("en-US", {
                      month: "long",
                      day: "numeric",
                      year: "numeric",
                    })
                  : "Unknown"}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {["Data", "Pipeline", "Annotations", "Evaluation", "Export"].map(
          (section) => (
            <Card key={section}>
              <CardHeader>
                <CardTitle className="text-base">{section}</CardTitle>
                <CardDescription>
                  {section} management coming soon
                </CardDescription>
              </CardHeader>
            </Card>
          )
        )}
      </div>
    </div>
  );
}
