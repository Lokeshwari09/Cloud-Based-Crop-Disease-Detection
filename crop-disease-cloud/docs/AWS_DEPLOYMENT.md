# Deploying on AWS (Console walkthrough)

Architecture: **EC2 instance** (runs Docker Compose: nginx + 3 API containers) -> **S3 bucket** (stores uploaded leaf photos) via an **IAM role** (no access keys on the server).

> These steps were written from the AWS Console flow but were **not executed** while building this project - screen labels can differ slightly by region/date. Region used below: `ap-south-1` (Mumbai); any region works.

## 1. Create the S3 bucket
1. Console -> **S3** -> **Create bucket**.
2. Name: globally unique, e.g. `crop-disease-uploads-<yourname>`; Region `ap-south-1`.
3. Keep **Block all public access = ON** (the app serves images itself, the bucket stays private).
4. Create bucket.

## 2. Create an IAM role for the server
1. Console -> **IAM** -> **Policies** -> **Create policy** -> JSON tab:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject"],
    "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/uploads/*"
  }]
}
```
   Name it `CropDiseaseS3Access`.
2. **IAM** -> **Roles** -> **Create role** -> trusted entity **AWS service -> EC2** -> attach `CropDiseaseS3Access` -> name `CropDiseaseEC2Role`.

## 3. Launch the EC2 instance
1. Console -> **EC2** -> **Launch instance**.
2. Name `crop-disease-server`; AMI **Ubuntu Server 24.04 LTS** (or 22.04).
3. Instance type `t3.micro` (or `t2.micro` where free-tier eligible).
4. Key pair: create/download a `.pem` file.
5. Network settings -> create a security group with inbound rules:
   - SSH (22) from **My IP**
   - Custom TCP **8080** from `0.0.0.0/0` (the web app)
6. **Advanced details -> IAM instance profile** -> `CropDiseaseEC2Role`.
7. Launch, then copy the instance **Public IPv4 address**.

## 4. Install Docker and start the project
From your laptop (PowerShell / terminal), copy the project zip and connect:
```bash
scp -i your-key.pem crop-disease-cloud.zip ubuntu@<PUBLIC_IP>:~
ssh -i your-key.pem ubuntu@<PUBLIC_IP>
```
On the server:
```bash
sudo apt-get update && sudo apt-get install -y unzip
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && exit        # log out, then ssh in again

unzip crop-disease-cloud.zip && cd crop-disease-cloud
cat > .env <<'EOF'
USE_S3=true
S3_BUCKET=YOUR-BUCKET-NAME
AWS_REGION=ap-south-1
EOF
docker compose up --build -d
docker compose ps
```

## 5. Verify
- Open `http://<PUBLIC_IP>:8080` - the dashboard should show **Amazon S3** as object storage.
- `curl http://<PUBLIC_IP>:8080/api/health` -> `"storage":"s3"`.
- Upload a leaf, then check the bucket in the S3 console: an `uploads/` folder with your image appears.
- Run the load test from your laptop: `python scripts/load_test.py --url http://<PUBLIC_IP>:8080 --requests 100` - the "Served by" table shows requests spread over the 3 containers.

## 6. Optional extensions (for the report / viva)
| Goal | AWS service |
|---|---|
| Several servers + health checks | **Application Load Balancer** + **Auto Scaling Group** (launch template = this EC2 setup) |
| Private container registry | **ECR** (`docker push`), then run on **ECS/Fargate** |
| Managed database instead of SQLite | **RDS (PostgreSQL)** or **DynamoDB** |
| Monitoring & alarms | **CloudWatch** (CPU alarm -> scale out, matches the CloudSim experiment) |
| HTTPS + custom domain | **Route 53** + **ACM** certificate on the load balancer |

## 7. Clean up (avoid charges)
Terminate the EC2 instance, empty then delete the S3 bucket, delete the IAM role/policy, release any Elastic IP.
