# aws-secretsmanager Skill

The `aws-secretsmanager` skill enforces MSK's standards for all AWS Secrets Manager secrets managed in Terraform. It ensures that every `aws_secretsmanager_secret` resource Copilot generates or reviews complies with MSK's rules, starting with the mandatory `user-` prefix requirement. The skill prevents non-compliant configurations from being created, rewrites existing violations to meet the standards, and refuses to produce any configuration that breaks MSK's defined Secrets Manager rules.
