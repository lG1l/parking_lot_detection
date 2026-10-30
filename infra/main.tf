terraform {
  required_version = "~> 1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "ap-northeast-2"
}

variable "name_prefix" {
  description = "리소스 이름 접두어. 같은 계정을 여러 팀이 쓰므로 값은 terraform.tfvars에만 둔다"
  type        = string
}

# 기본 VPC는 새로 만들지 않고 조회만 한다 (2.7)
data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "backend" {
  name        = "${var.name_prefix}-backend"
  description = "backend EC2"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_security_group" "gpu" {
  name        = "${var.name_prefix}-gpu"
  description = "GPU EC2"
  vpc_id      = data.aws_vpc.default.id
}

# 백엔드 인바운드: uvicorn 8000·SSH는 전체, 5432는 GPU 보안 그룹에서만 (D-17, D-133)
resource "aws_vpc_security_group_ingress_rule" "backend_http" {
  security_group_id = aws_security_group.backend.id
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "backend_ssh" {
  security_group_id = aws_security_group.backend.id
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "backend_postgres_from_gpu" {
  security_group_id            = aws_security_group.backend.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.gpu.id
}

# GPU 인바운드: SSH만 (D-133)
resource "aws_vpc_security_group_ingress_rule" "gpu_ssh" {
  security_group_id = aws_security_group.gpu.id
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "0.0.0.0/0"
}

# 아웃바운드: 두 인스턴스 모두 전체 허용
resource "aws_vpc_security_group_egress_rule" "backend_all" {
  security_group_id = aws_security_group.backend.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "gpu_all" {
  security_group_id = aws_security_group.gpu.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
