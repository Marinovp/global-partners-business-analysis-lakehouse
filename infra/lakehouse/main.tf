data "aws_caller_identity" "current" {}

locals {
  name_prefix = "gp-lakehouse-${var.environment}"
}
