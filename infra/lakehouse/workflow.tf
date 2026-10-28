# The pipeline: one workflow run executes the jobs in order, each starting only after the
# previous one SUCCEEDED. max_concurrent_runs = 1 so two runs never overlap.
resource "aws_glue_workflow" "pipeline" {
  name                = "${local.name_prefix}-pipeline"
  max_concurrent_runs = 1

  tags = {
    Name = "${local.name_prefix}-pipeline"
  }
}

# Entry point: started by hand with `make pipeline` (becomes a daily SCHEDULED trigger later).
resource "aws_glue_trigger" "start" {
  name          = "${local.name_prefix}-start"
  workflow_name = aws_glue_workflow.pipeline.name
  type          = "ON_DEMAND"

  actions {
    job_name = aws_glue_job.extract.name
  }
}

# CONDITIONAL, starts silver when extract SUCCEEDED.
resource "aws_glue_trigger" "after_extract" {
  name              = "${local.name_prefix}-after-extract"
  workflow_name     = aws_glue_workflow.pipeline.name
  type              = "CONDITIONAL"
  start_on_creation = true

  predicate {
    conditions {
      job_name = aws_glue_job.extract.name
      state    = "SUCCEEDED"
    }
  }

  actions {
    job_name = aws_glue_job.silver.name
  }
}
