resource "aws_security_group" "glue" {
  name        = "${local.name_prefix}-glue-sg"
  description = "Glue Job network interface security group"
  vpc_id      = aws_vpc.lakehouse.id

  tags = {
    Name = "${local.name_prefix}-glue-sg"
  }
}

# Required by Glue: Spark driver and workers talk to each other on any TCP port
# so we need to allow all traffic within the security group.
resource "aws_vpc_security_group_ingress_rule" "glue_self" {
  security_group_id            = aws_security_group.glue.id
  referenced_security_group_id = aws_security_group.glue.id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
}

resource "aws_vpc_security_group_egress_rule" "glue_all" {
  ip_protocol       = "-1" # allow all protocols
  security_group_id = aws_security_group.glue.id
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "RDS network interface security group"
  vpc_id      = aws_vpc.lakehouse.id

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

resource "aws_security_group" "endpoints" {
  name        = "${local.name_prefix}-endpoints-sg"
  description = "Endpoints network interface security group"
  vpc_id      = aws_vpc.lakehouse.id

  tags = {
    Name = "${local.name_prefix}-endpoints-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_glue" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.glue.id
  ip_protocol                  = "tcp"
  from_port                    = 1433
  to_port                      = 1433
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_from_glue" {
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.glue.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
