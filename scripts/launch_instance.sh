#!/bin/bash
# launch_instance.sh — launch a Prism audit instance on p5 or trn2.
#
# Usage:
#   launch_instance.sh p5          # p5.48xlarge, CUDA rail, us-east-1
#   launch_instance.sh trn2        # trn2.48xlarge, Neuron rail, us-east-1
#
# Prerequisites (verified before launch):
#   - prism-ssm-role instance profile exists
#   - Running On-Demand P/Trn quota >= 192 vCPU in region
#   - $AWS_PROFILE set (default: prism)
#
# AMI IDs are pinned as of 2026-04-21. Refresh via
#   aws ec2 describe-images --owners amazon --filters ...

set -euo pipefail

RAIL="${1:?usage: launch_instance.sh {p5|trn2}}"
: "${AWS_PROFILE:=prism}"
: "${AWS_REGION:=us-east-1}"

case "$RAIL" in
  p5)
    INSTANCE_TYPE=p5.48xlarge
    AMI_ID=ami-09d0a18beb02cc7d4   # DLAMI GPU PyTorch 2.7 Ubuntu 22.04 (2026-04-19)
    USERDATA=cloud-init/p5-userdata.sh
    NAME_TAG=prism-p5
    QUOTA_CODE=L-417A185B
    ;;
  trn2)
    INSTANCE_TYPE=trn2.48xlarge
    AMI_ID=ami-0fd664467b3cf8dfd   # DLAMI Neuron Ubuntu 22.04 (2026-02-27)
    USERDATA=cloud-init/trn2-userdata.sh
    NAME_TAG=prism-trn2
    QUOTA_CODE=L-2C3B7624
    ;;
  *) echo "unknown rail: $RAIL (expected p5 or trn2)" >&2; exit 2 ;;
esac

here=$(cd "$(dirname "$0")/.." && pwd)
userdata_path="${here}/${USERDATA}"

# Preflight: quota check
quota=$(aws service-quotas get-service-quota \
  --service-code ec2 --quota-code "$QUOTA_CODE" \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --query 'Quota.Value' --output text)
if (( $(printf '%.0f' "$quota") < 192 )); then
  echo "ERR: quota $QUOTA_CODE is $quota in $AWS_REGION; need >= 192" >&2
  echo "     File at https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas" >&2
  exit 4
fi

# Preflight: instance profile
aws iam get-instance-profile --instance-profile-name prism-ssm-role \
  --profile "$AWS_PROFILE" >/dev/null 2>&1 || {
  echo "ERR: instance profile prism-ssm-role missing. Create from root IAM console." >&2
  exit 5
}

# Security group: outbound-only. Create if missing.
sg_id=$(aws ec2 describe-security-groups \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filters "Name=group-name,Values=prism-audit-sg" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [[ "$sg_id" == "None" || -z "$sg_id" ]]; then
  vpc_id=$(aws ec2 describe-vpcs \
    --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    --filters "Name=is-default,Values=true" \
    --query 'Vpcs[0].VpcId' --output text)
  sg_id=$(aws ec2 create-security-group \
    --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    --group-name prism-audit-sg \
    --description "Prism audit instance SG — outbound 443 only (SSM)" \
    --vpc-group-id "$vpc_id" \
    --query 'GroupId' --output text)
  # Default SG has allow-all-egress; revoke and re-add 443-only
  aws ec2 revoke-security-group-egress \
    --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    --group-id "$sg_id" \
    --ip-permissions IpProtocol=-1,IpRanges='[{CidrIp=0.0.0.0/0}]' 2>/dev/null || true
  aws ec2 authorize-security-group-egress \
    --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    --group-id "$sg_id" \
    --ip-permissions 'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0,Description="SSM + github"}]'
  echo "created sg $sg_id (443 egress only)"
fi

# Launch
echo "launching $INSTANCE_TYPE in $AWS_REGION with AMI $AMI_ID..."
instance_id=$(aws ec2 run-instances \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --iam-instance-profile Name=prism-ssm-role \
  --security-group-ids "$sg_id" \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=500,VolumeType=gp3,DeleteOnTermination=true}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=prism},{Key=CostCenter,Value=goatnote-hackathon-2026-04}]" \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1' \
  --user-data "file://${userdata_path}" \
  --query 'Instances[0].InstanceId' --output text)

echo "launched $instance_id"
echo "waiting for running state..."
aws ec2 wait instance-running \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --instance-ids "$instance_id"

echo "instance running; SSM registration may take 60–90s"
echo "poll readiness: make ssm-ping RAIL=${RAIL}"
