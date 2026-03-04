import { useParams } from "react-router-dom";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import NlpQueriesSection from "@/projects/evaluation/NlpQueriesSection";
import PredictorConfigSection from "@/projects/evaluation/PredictorConfigSection";
import SessionsSection from "@/projects/evaluation/SessionsSection";
import ValidatedPredictorsSection from "@/projects/evaluation/ValidatedPredictorsSection";

export default function EvaluationPage() {
  const { projectId } = useParams<{ projectId: string }>();

  return (
    <div className="space-y-8">
      <WorkflowBreadcrumb currentStep="evaluation" projectId={projectId!} />
      <div>
        <h2 className="text-lg font-semibold text-foreground">Evaluation Workflow</h2>
        <p className="text-sm text-muted-foreground">
          Configure NLP queries, set up predictors, evaluate accuracy, and activate for production
        </p>
      </div>

      <NlpQueriesSection projectId={projectId!} />

      <hr className="border-border" />

      <PredictorConfigSection projectId={projectId!} />

      <hr className="border-border" />

      <SessionsSection projectId={projectId!} />

      <hr className="border-border" />

      <ValidatedPredictorsSection projectId={projectId!} />
    </div>
  );
}
