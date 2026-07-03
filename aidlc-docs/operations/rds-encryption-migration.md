# RDS Encrypted Storage Migration Runbook

**Scope**: Migrate the live DocSuri PostgreSQL instance from unencrypted RDS storage to encrypted RDS storage.
**Status**: Operator-run migration. Do not execute as an automatic CDK property flip.

## Why This Is Separate

The live RDS instances currently report `StorageEncrypted=false`. Existing RDS storage encryption cannot be enabled in place. A blind CDK change on the existing `Postgres` resource risks replacement-class behavior and a blank/new database cutover. Use an encrypted snapshot restore with an explicit app cutover instead.

## Preconditions

- Freeze production writes: API, ingestion, summary, and novelty workers must be stopped or in maintenance mode.
- Confirm latest successful backup and take a fresh manual snapshot.
- Confirm the target KMS key. The default AWS-managed RDS key is acceptable unless compliance requires a CMK.
- Capture current DB metadata:

```bash
aws rds describe-db-instances \
  --db-instance-identifier docsuri-compute-postgres9dc8bb04-7ajkntsj0ouu \
  --profile AdministratorAccess-028317349537 \
  --region ap-northeast-2 \
  --query 'DBInstances[0].{subnetGroup:DBSubnetGroup.DBSubnetGroupName,securityGroups:VpcSecurityGroups[].VpcSecurityGroupId,parameterGroups:DBParameterGroups[].DBParameterGroupName,optionGroups:OptionGroupMemberships[].OptionGroupName,class:DBInstanceClass,engine:Engine,engineVersion:EngineVersion,multiAZ:MultiAZ,storageType:StorageType,allocatedStorage:AllocatedStorage}'
```

## Migration Steps

1. Create a final unencrypted manual snapshot.

```bash
aws rds create-db-snapshot \
  --db-instance-identifier docsuri-compute-postgres9dc8bb04-7ajkntsj0ouu \
  --db-snapshot-identifier docsuri-final-unencrypted-$(date +%Y%m%d%H%M%S) \
  --profile AdministratorAccess-028317349537 \
  --region ap-northeast-2
```

2. Copy that snapshot with encryption enabled.

```bash
aws rds copy-db-snapshot \
  --source-db-snapshot-identifier <final-snapshot-arn-or-id> \
  --target-db-snapshot-identifier docsuri-final-encrypted-<yyyymmddhhmmss> \
  --kms-key-id alias/aws/rds \
  --copy-tags \
  --source-region ap-northeast-2 \
  --profile AdministratorAccess-028317349537 \
  --region ap-northeast-2
```

3. Restore a parallel encrypted DB from the encrypted snapshot, using the captured subnet group, security groups, class, Multi-AZ setting, and parameter/option groups.

```bash
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier docsuri-postgres-encrypted-<yyyymmddhhmmss> \
  --db-snapshot-identifier docsuri-final-encrypted-<yyyymmddhhmmss> \
  --db-instance-class db.t4g.small \
  --db-subnet-group-name <captured-subnet-group> \
  --vpc-security-group-ids <captured-security-group-id> \
  --multi-az \
  --no-publicly-accessible \
  --profile AdministratorAccess-028317349537 \
  --region ap-northeast-2
```

4. Verify the restored DB before traffic cutover.

```bash
aws rds describe-db-instances \
  --db-instance-identifier docsuri-postgres-encrypted-<yyyymmddhhmmss> \
  --profile AdministratorAccess-028317349537 \
  --region ap-northeast-2 \
  --query 'DBInstances[0].{status:DBInstanceStatus,encrypted:StorageEncrypted,multiAZ:MultiAZ,public:PubliclyAccessible,endpoint:Endpoint.Address}'
```

5. Cut over application configuration in a dedicated PR/deploy:

- Update `Docsuri-Compute` to use or import the encrypted DB endpoint/secret.
- Update hardcoded DB references in `ops/cdk/stacks/ingestion_stack.py` and `ops/cdk/stacks/summarization_stack.py`.
- Run `cdk diff` and confirm no destructive replacement of the encrypted DB.
- Deploy with workers paused, then run migrations/readiness checks.

6. Post-cutover validation:

- `GET /readyz` returns ready.
- Auth login/session read works.
- Library/search history reads work.
- Ingestion can process one canary job.
- Summary worker can read glossary and emit CloudWatch metrics.
- `StorageEncrypted=true` on the active DB.

7. Decommission the old unencrypted DB only after the retention window and explicit operator approval.

## Rollback

Rollback before old DB decommission: stop services, point the app back to the old endpoint/secret, redeploy, and verify `/readyz`. Do not delete the old DB or final snapshots until rollback is no longer needed.
