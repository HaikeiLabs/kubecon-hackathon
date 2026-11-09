terraform {
  required_version = "1.15.8"

  backend "s3" {
    bucket       = "kei-terraform-state-726299224953"
    key          = "kubecon-hackathon/friction-desk/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.100.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

