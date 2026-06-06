variable "environment" {
  type = string
}

variable "identifier" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "allowed_cidr_blocks" {
  type = list(string)
}

variable "instance_class" {
  type    = string
  default = "db.t4g.large"
}

variable "allocated_storage" {
  type    = number
  default = 100
}

variable "db_name" {
  type    = string
  default = "vela"
}

variable "tags" {
  type    = map(string)
  default = {}
}
