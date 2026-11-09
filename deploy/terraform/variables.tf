variable "aws_region" {
  description = "AWS region containing ECR and Secrets Manager resources."
  type        = string
  default     = "us-east-1"
}

variable "keep_ecr" {
  description = "Keep the ECR repository. Set false only for deliberate Terraform-managed removal."
  type        = bool
  default     = true
}

variable "allow_ecr_force_delete" {
  description = "Explicitly allow Terraform to delete the ECR repository and all its images."
  type        = bool
  default     = false
}
