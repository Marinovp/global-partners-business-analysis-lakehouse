# The pipeline: one workflow run executes the jobs in order, each starting only after the
# previous one SUCCEEDED. max_concurrent_runs = 1 so two runs never overlap.
resource "aws_glue_workflow" "pipeline" {
  name                = "${local.name_prefix}-pipeline"
  max_concurrent_runs = 1

  tags = {
    Name = "${local.name_prefix}-pipeline"
  }
}

# Entry point: runs daily at 06:00 UTC while the stack exists; `make pipeline` starts a run on demand.
resource "aws_glue_trigger" "start" {
  name              = "${local.name_prefix}-start"
  workflow_name     = aws_glue_workflow.pipeline.name
  type              = "SCHEDULED"
  schedule          = "cron(0 6 * * ? *)"
  start_on_creation = true

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

# Starts gold only after silver SUCCEEDED.
resource "aws_glue_trigger" "after_silver" {
  name              = "${local.name_prefix}-after-silver"
  workflow_name     = aws_glue_workflow.pipeline.name
  type              = "CONDITIONAL"
  start_on_creation = true

  predicate {
    conditions {
      job_name = aws_glue_job.silver.name
      state    = "SUCCEEDED"
    }
  }

  actions {
    job_name = aws_glue_job.gold.name
  }
}

# Starts the DQ gate only after gold SUCCEEDED.
resource "aws_glue_trigger" "after_gold" {
  name              = "${local.name_prefix}-after-gold"
  workflow_name     = aws_glue_workflow.pipeline.name
  type              = "CONDITIONAL"
  start_on_creation = true

  predicate {
    conditions {
      job_name = aws_glue_job.gold.name
      state    = "SUCCEEDED"
    }
  }

  actions {
    job_name = aws_glue_job.dq.name
  }
}
