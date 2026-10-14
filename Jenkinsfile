pipeline {
    agent any

    environment {
        // Change 'bhashkarsingh' to your Docker Hub username or AWS ECR URI
        DOCKER_HUB_USER        = 'bhashkarsingh'
        APP_NAME               = 'drug-tariff-analytics'
        IMAGE_NAME             = "${DOCKER_HUB_USER}/${APP_NAME}"
        IMAGE_TAG              = "${BUILD_NUMBER}"
        DOCKER_CREDENTIALS_ID  = 'dockerhub-credentials'
        KUBECONFIG             = "${HOME}/.kube/config"
    }

    options {
        timestamps()
        timeout(time: 15, unit: 'MINUTES')
        ansiColor('xterm')
    }

    stages {
        stage('Checkout') {
            steps {
                echo "==> Pulling latest code from GitHub..."
                checkout scm
            }
        }

        stage('Build & Test') {
            steps {
                echo "==> Setting up environment and running tests..."
                sh '''
                    python3 -m venv .jenkins_venv
                    .jenkins_venv/bin/pip install --upgrade pip
                    .jenkins_venv/bin/pip install -r requirements-dev.txt
                    .jenkins_venv/bin/pytest -v
                    rm -rf .jenkins_venv
                '''
            }
        }

        stage('Docker Build') {
            steps {
                echo "==> Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG} and latest..."
                sh '''
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} -t ${IMAGE_NAME}:latest .
                '''
            }
        }

        stage('Push Image') {
            steps {
                echo "==> Logging in and pushing Docker image to registry..."
                withCredentials([usernamePassword(
                    credentialsId: DOCKER_CREDENTIALS_ID,
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                        echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin
                        docker push ${IMAGE_NAME}:${IMAGE_TAG}
                        docker push ${IMAGE_NAME}:latest
                        docker logout
                    '''
                }
            }
        }

        stage('Deploy to Minikube') {
            steps {
                echo "==> Deploying application to Minikube..."
                sh '''
                    # Substitute image placeholder in deployment manifest with built tag
                    sed "s|DOCKER_IMAGE_PLACEHOLDER|${IMAGE_NAME}:${IMAGE_TAG}|g" k8s/deployment.yaml > k8s/deployment-applied.yaml

                    # Apply manifests to Minikube cluster
                    kubectl apply -f k8s/deployment-applied.yaml
                    kubectl apply -f k8s/service.yaml
                    rm -f k8s/deployment-applied.yaml
                '''
            }
        }

        stage('Verification') {
            steps {
                echo "==> Verifying Deployment rollout and service status..."
                sh '''
                    # Wait for rollout to complete
                    kubectl rollout status deployment/drug-tariff-analytics --timeout=120s

                    # Display running pods and service details
                    echo "=== Running Pods ==="
                    kubectl get pods -l app=drug-tariff-analytics -o wide

                    echo "=== Kubernetes Service ==="
                    kubectl get svc drug-tariff-service

                    # Health check verification
                    echo "=== Minikube NodePort Health Check ==="
                    NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
                    NODE_PORT=$(kubectl get svc drug-tariff-service -o jsonpath='{.spec.ports[0].nodePort}')
                    echo "Target URL: http://${NODE_IP}:${NODE_PORT}/healthz"
                    curl -s -f "http://${NODE_IP}:${NODE_PORT}/healthz" || echo "Note: If running on remote AWS EC2, access via EC2_PUBLIC_IP:${NODE_PORT} or use 'minikube service drug-tariff-service --url'"
                '''
            }
        }
    }

    post {
        always {
            echo "==> Pipeline run finished."
            sh '''
                # Clean up dangling images to save disk space
                docker image prune -f || true
            '''
        }
        success {
            echo "==> CI/CD Pipeline Completed Successfully! Application is live."
        }
        failure {
            echo "==> CI/CD Pipeline Failed. Check stage logs above for details."
        }
    }
}
