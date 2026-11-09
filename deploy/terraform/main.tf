resource "aws_ecr_repository" "friction_desk" {
  count                = var.keep_ecr ? 1 : 0
  name                 = "kei/kubecon-hackathon-friction-desk"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.allow_ecr_force_delete

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "friction_desk" {
  count      = var.keep_ecr ? 1 : 0
  repository = aws_ecr_repository.friction_desk[0].name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after 14 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    }]
  })
}

# Metadata only: secret values are created and rotated out-of-band in Secrets Manager.
resource "aws_secretsmanager_secret" "elasticsearch" {
  name                    = "kubecon-hackathon/friction-desk-elasticsearch"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "kea_runtime" {
  name                    = "kubecon-hackathon/friction-desk-kea-runtime"
  recovery_window_in_days = 7
}

output "image_repository" {
  description = "Dedicated ECR repository URI for the API image."
  value       = try(aws_ecr_repository.friction_desk[0].repository_url, null)
}
