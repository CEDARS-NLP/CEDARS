provider "aws" {
  region = var.region

  # Guard against applying to the wrong account. Verified target:
  # 180294205688 (AWS profile `saml`). Override via var.allowed_account_ids
  # if the account changes.
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = {
      Project     = "cedars-v2"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "cedars"
    }
  }
}
