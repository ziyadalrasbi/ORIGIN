# Cost Estimate: 10K Song Pilot

## Overview
Processing 10,000 songs through ORIGIN API:
- 10,000 `/v1/ingest` calls (content submission + decision)
- 10,000 `/v1/evidence-packs` calls (generate JSON, PDF, HTML)

---

## Resource Requirements

### Per-Song Processing
- **Ingest API Call:**
  - Database operations: ~50ms
  - ML inference (scikit-learn/xgboost): ~10-20ms
  - Certificate generation: ~5ms
  - Total: ~65-75ms per request

- **Evidence Pack Generation:**
  - JSON generation: ~5ms
  - PDF generation (reportlab): ~100-200ms (CPU-intensive)
  - HTML generation: ~10ms
  - File I/O: ~20ms
  - Total: ~135-235ms per evidence pack

### Storage Requirements
- **Database per upload:** ~2-3KB (upload record + related tables)
- **Evidence packs per song:** 
  - JSON: ~1KB
  - PDF: ~2-3KB
  - HTML: ~2KB
  - Total: ~5-6KB per evidence pack

**Total storage:**
- Database: 10,000 × 3KB = ~30MB
- Evidence packs: 10,000 × 6KB = ~60MB
- **Total: ~90MB**

### Compute Requirements
- **Total processing time:**
  - Ingest: 10,000 × 70ms = ~12 minutes (sequential)
  - Evidence packs: 10,000 × 180ms = ~30 minutes (sequential)
  - **Total: ~42 minutes sequential, or ~5-10 minutes with parallelization**

- **Peak resource usage:**
  - CPU: 2-4 cores (for PDF generation)
  - RAM: 2-4GB (for ML models + processing)
  - I/O: Moderate (database + file writes)

---

## Cost Scenarios

### Scenario 1: Self-Hosted (On-Premises/Your Own Server)
**Cost: $0 - $50**

- **Infrastructure:** Use existing servers or rent a VPS
- **Compute:** 
  - Small VPS (4 vCPU, 8GB RAM): $20-40/month
  - Can process 10K songs in a few hours
- **Storage:** Included in VPS
- **Total:** $20-40 for the month (can process multiple pilots)

**Best for:** Testing, development, small pilots

---

### Scenario 2: AWS Deployment

#### Option A: EC2 + RDS + S3 (Managed)
**Estimated Cost: $150 - $300**

**Compute:**
- EC2 t3.medium (2 vCPU, 4GB RAM): $0.0416/hour
  - Processing time: ~2-4 hours for 10K songs
  - Cost: ~$0.20-0.30

**Database:**
- RDS db.t3.micro (PostgreSQL): $0.017/hour
  - Running for pilot duration: ~$0.10-0.20

**Storage:**
- S3 Standard: $0.023/GB/month
  - 90MB = $0.002/month (negligible)

**Redis:**
- ElastiCache cache.t3.micro: $0.017/hour
  - ~$0.10-0.20

**Total: ~$0.50-0.90 for processing + $50-100 setup/monthly minimums**

#### Option B: ECS Fargate (Serverless Containers)
**Estimated Cost: $100 - $200**

- Fargate: $0.04/vCPU-hour + $0.004/GB-hour
- Processing 10K songs: ~$5-10 compute
- RDS + S3: Same as above
- **Total: ~$60-120** (more efficient, pay-per-use)

---

### Scenario 3: Google Cloud Platform

#### Cloud Run (Serverless Containers)
**Estimated Cost: $50 - $150**

- Cloud Run: $0.00002400/vCPU-second + $0.00000250/GB-second
- Processing 10K songs: ~$3-8
- Cloud SQL (PostgreSQL): $0.025/hour = ~$0.15-0.30
- Cloud Storage: $0.020/GB/month = ~$0.002
- **Total: ~$20-50** (very cost-effective for variable workloads)

---

### Scenario 4: Azure

#### Azure Container Instances + Azure Database
**Estimated Cost: $100 - $250**

- Container Instances: ~$0.05-0.10/hour
- Azure Database for PostgreSQL: ~$0.10-0.20/hour
- Azure Blob Storage: ~$0.018/GB/month
- **Total: ~$80-200**

---

## Recommended Approach for Pilot

### **Best Value: Google Cloud Run**
**Estimated Total: $30-60**

**Why:**
- Pay only for actual processing time
- No minimum commitments
- Auto-scales to zero when not in use
- Easy to set up and tear down

**Setup:**
1. Deploy containers to Cloud Run
2. Use Cloud SQL for PostgreSQL (or Cloud SQL for PostgreSQL)
3. Use Cloud Storage for evidence packs
4. Process 10K songs over a few hours
5. Total cost: ~$30-60

---

## Cost Breakdown Summary

| Provider | Compute | Database | Storage | **Total** |
|----------|---------|----------|---------|-----------|
| **Self-Hosted VPS** | $20-40/mo | Included | Included | **$20-40** |
| **AWS EC2** | $0.20-0.30 | $0.10-0.20 | $0.002 | **$0.50-0.90** + setup |
| **AWS Fargate** | $5-10 | $0.10-0.20 | $0.002 | **$60-120** |
| **GCP Cloud Run** | $3-8 | $0.15-0.30 | $0.002 | **$30-60** ⭐ |
| **Azure Containers** | $5-10 | $0.15-0.30 | $0.002 | **$80-200** |

*Note: AWS/Azure costs assume minimal monthly commitments. Actual costs may be higher due to minimum billing periods.*

---

## Additional Considerations

### Scaling for Production
- **10K songs:** Current setup handles easily
- **100K songs:** May need 2-4x resources
- **1M songs:** Consider dedicated infrastructure or auto-scaling

### Cost Optimization Tips
1. **Batch processing:** Process in batches to optimize resource usage
2. **Use spot/preemptible instances:** 60-90% cost savings (AWS Spot, GCP Preemptible)
3. **Reserved instances:** If running continuously, save 30-50%
4. **Storage tiering:** Move old evidence packs to cheaper storage (S3 Glacier, etc.)

### Hidden Costs to Consider
- **Data transfer:** Usually free within same region, ~$0.09/GB outbound
- **Monitoring/logging:** CloudWatch/Stackdriver: ~$5-20/month
- **Backup:** Database backups: ~$5-15/month
- **SSL certificates:** Free with Let's Encrypt

---

## Recommendation

**For a 10K song pilot:**
- **Best option:** Google Cloud Run (~$30-60)
- **Budget option:** Self-hosted VPS (~$20-40/month)
- **Enterprise option:** AWS Fargate (~$60-120)

**Expected processing time:** 2-4 hours for 10K songs with proper parallelization.

---

## Next Steps

1. Choose deployment platform
2. Set up infrastructure (1-2 hours)
3. Run pilot batch
4. Monitor costs in real-time
5. Scale as needed

**Total pilot cost estimate: $30-120 depending on platform choice.**


