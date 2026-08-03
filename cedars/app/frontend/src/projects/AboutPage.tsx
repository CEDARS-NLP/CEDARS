import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Static "About" page (ports the original about.html content). */
export default function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="mb-6 flex items-center gap-3">
        <img src="/cedars-logo.png" alt="CEDARS" className="h-9 w-9 dark:invert" />
        <h1 className="text-2xl font-bold text-foreground">About CEDARS</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Clinical Event Detection and Recording System</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
          <p>
            CEDARS is an NLP-powered platform for identifying and annotating
            clinical events in electronic health records. It combines automated
            keyword and negation detection with a human-in-the-loop review
            workflow so researchers can efficiently build event-annotated cohorts.
          </p>
          <p>
            The standard workflow is: upload clinical notes, define a search
            query, run NLP processing, adjudicate the resulting annotations one
            patient at a time, review cohort statistics, and export the
            annotated results.
          </p>
          <p>
            For documentation and source code, see the CEDARS project
            repository.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
