########################################################################
# Internal ALB. Path-based routing:
#   /api/*, /ws/*  -> backend target group (WebSockets on /ws)
#   /*             -> frontend target group (static SPA)
#
# Because the ALB routes /api and /ws directly to the backend, the
# proxy_pass blocks in frontend/nginx.conf are never exercised (the ALB
# intercepts those paths first). Frontend only serves static assets here.
########################################################################

resource "aws_lb" "main" {
  name               = "${local.prefix}-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.private_subnet_ids

  idle_timeout = 300 # allow long-lived WebSocket progress streams

  tags = { Name = "${local.prefix}-alb" }
}

# ---- Target groups ----
resource "aws_lb_target_group" "backend" {
  name        = "${local.prefix}-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Fargate awsvpc

  health_check {
    path                = "/api/v1/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Sticky sessions help keep a WebSocket-upgraded client on one backend task.
  stickiness {
    type            = "lb_cookie"
    enabled         = true
    cookie_duration = 3600
  }
}

resource "aws_lb_target_group" "frontend" {
  name        = "${local.prefix}-frontend"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# ---- Listener (default -> frontend). HTTPS:443 when enable_https, else HTTP:80.
# For a spike, leave enable_https=false: no cert needed, reach the app via the
# ALB's AWS-generated DNS name (see the alb_dns_name output) over http://.
resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.alb_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

resource "aws_lb_listener" "http" {
  count             = var.enable_https ? 0 : 1
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

locals {
  # The active listener ARN, whichever protocol is enabled.
  alb_listener_arn = var.enable_https ? aws_lb_listener.https[0].arn : aws_lb_listener.http[0].arn
}

# ---- Route /api/* and /ws/* to backend ----
resource "aws_lb_listener_rule" "backend" {
  listener_arn = local.alb_listener_arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/ws/*"]
    }
  }
}

# ---- DNS record (optional) ----
resource "aws_route53_record" "app" {
  count   = var.route53_zone_id != "" && var.app_hostname != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.app_hostname
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
