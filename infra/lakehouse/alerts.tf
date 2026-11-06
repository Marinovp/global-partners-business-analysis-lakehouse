# Failure alerting: Glue Workflows can't notify on their own, so an EventBridge rule watches
# every pipeline job and forwards FAILED / TIMEOUT / ERROR events to an SNS topic (email).
resource "aws_sns_topic" "alerts" {
  # Not KMS-encrypted on purpose: the messages carry job names and states, not data, and
  # EventBridge can't publish to a topic encrypted with the AWS-managed SNS key.
  name = "${local.name_prefix}-pipeline-alerts"

  tags = {
    Name = "${local.name_prefix}-pipeline-alerts"
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowEventBridgePublish"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.job_failed.arn } }
    }]
  })
}

# Only created when an address is provided (AWS sends a confirmation email that must be clicked).
resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_event_rule" "job_failed" {
  name        = "${local.name_prefix}-job-failed"
  description = "A lakehouse pipeline job failed, timed out or errored."

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      state   = ["FAILED", "TIMEOUT", "ERROR"]
      jobName = [aws_glue_job.extract.name, aws_glue_job.silver.name, aws_glue_job.gold.name, aws_glue_job.dq.name]
    }
  })
}

resource "aws_cloudwatch_event_target" "alerts" {
  rule = aws_cloudwatch_event_rule.job_failed.name
  arn  = aws_sns_topic.alerts.arn

  input_transformer {
    input_paths = {
      job   = "$.detail.jobName"
      state = "$.detail.state"
      run   = "$.detail.jobRunId"
      msg   = "$.detail.message"
    }
    input_template = "\"Pipeline job <job> <state> (run <run>): <msg>. Fix the cause, then resume or re-run the workflow.\""
  }
}
