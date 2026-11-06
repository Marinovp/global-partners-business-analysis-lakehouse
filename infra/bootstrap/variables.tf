variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "us-west-2"
}

variable "github_repo" {
  description = "GitHub repository (owner/name) whose workflows may assume the deploy role."
  type        = string
  default     = "Marinovp/global-partners-business-analysis-lakehouse"
}
