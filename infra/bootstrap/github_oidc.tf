# Lets GitHub Actions deploy without stored AWS keys: GitHub issues a short-lived OIDC token,
# AWS exchanges it for temporary credentials of the role below. Lives in the bootstrap stack
# because it must survive the daily destroy of the lakehouse stack.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_actions" {
  name = "gp-lakehouse-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        # Only workflows in this repository can use the role.
        StringLike = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*" }
      }
    }]
  })
}

# Terraform manages VPC, RDS, S3, KMS, Glue, Athena, SNS and EventBridge.
resource "aws_iam_role_policy_attachment" "github_power_user" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# PowerUserAccess excludes IAM, so allow it only for this project's own roles (gp-lakehouse-*).
resource "aws_iam_role_policy" "github_project_iam" {
  name = "gp-lakehouse-project-iam"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ManageProjectRoles"
        Effect   = "Allow"
        Action   = ["iam:*Role*", "iam:PassRole", "iam:TagRole", "iam:UntagRole"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/gp-lakehouse-*"
      },
      {
        Sid      = "ReadIamForPlans"
        Effect   = "Allow"
        Action   = ["iam:Get*", "iam:List*"]
        Resource = "*"
      },
    ]
  })
}
