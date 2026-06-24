"""OpenSearch domain — infra-design.md §1.

m6g.large.search ×2 (Multi-AZ), k-NN 1024-dim HNSW + BM25, VPC endpoint,
Fine-Grained Access Control, TLS + encryption at rest."""

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_opensearchservice as opensearch
from constructs import Construct


class SearchStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.IVpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._sg = ec2.SecurityGroup(
            self, "OpenSearchSg",
            vpc=vpc,
            description="OpenSearch domain - inbound HTTPS from ECS tasks only",
            allow_all_outbound=False,
        )

        self.domain = opensearch.Domain(
            self, "PapersDomain",
            domain_name="docsuri-papers",
            # 2.19 for disk-based vector search (mode=on_disk, compression_level=4x) — ~4x k-NN
            # RAM cut for full-body multi-chunk indexing, with NO app-side byte-vector plumbing.
            version=opensearch.EngineVersion.open_search("2.19"),
            vpc=vpc,
            vpc_subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)],
            security_groups=[self._sg],
            capacity=opensearch.CapacityConfig(
                data_node_instance_type="m6g.large.search",
                data_nodes=2,  # Multi-AZ
            ),
            ebs=opensearch.EbsOptions(
                volume_size=50,  # GB per node
                volume_type=ec2.EbsDeviceVolumeType.GP3,
            ),
            zone_awareness=opensearch.ZoneAwarenessConfig(
                availability_zone_count=2,
            ),
            encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
            node_to_node_encryption=True,
            enforce_https=True,
            fine_grained_access_control=opensearch.AdvancedSecurityOptions(
                master_user_arn=None,  # IAM-based FGAC (no internal DB user)
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

    @property
    def security_group(self) -> ec2.ISecurityGroup:
        return self._sg
