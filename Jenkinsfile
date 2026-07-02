pipeline {
    agent any

    environment {
        DOCKER_USERNAME = "hemanthkumarm3"

        EXPENSE_IMAGE = "hemanthkumarm3/expense-tracker"
        DIGITAL_IMAGE = "hemanthkumarm3/digital-twin"

        IMAGE_TAG = "${BUILD_NUMBER}"
    }

    stages {

        stage('Checkout Source') {
            steps {
                checkout scm
            }
        }

        stage('SonarQube Scan') {
            steps {
                script {
                    def scannerHome = tool 'sonar-scanner'

                    withSonarQubeEnv('sonarqube') {
                        sh """
                        ${scannerHome}/bin/sonar-scanner \
                        -Dsonar.projectKey=Devsecops-Project \
                        -Dsonar.projectName=Devsecops-Project \
                        -Dsonar.sources=.
                        """
                    }
                }
            }
        }

        stage('Quality Gate') {
            steps {
                timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: false
                }
            }
        }

        stage('Trivy File Scan') {
            steps {
                sh '''
                trivy fs . > trivy-filesystem-report.txt
                '''
            }
        }

        stage('Build Expense Tracker') {
            steps {
                sh '''
                docker build \
                -t ${EXPENSE_IMAGE}:${IMAGE_TAG} \
                -t ${EXPENSE_IMAGE}:latest \
                -f Expense-Tracker-with-Analytics-Dashboard/Dockerfile \
                Expense-Tracker-with-Analytics-Dashboard
                '''
            }
        }

        stage('Scan Expense Image') {
            steps {
                sh '''
                trivy image ${EXPENSE_IMAGE}:${IMAGE_TAG}
                '''
            }
        }

        stage('Build Digital Twin') {
            steps {
                sh '''
                docker build \
                -t ${DIGITAL_IMAGE}:${IMAGE_TAG} \
                -t ${DIGITAL_IMAGE}:latest \
                -f Digital-twin-of-expense-tracker/Dockerfile \
                Digital-twin-of-expense-tracker
                '''
            }
        }

        stage('Scan Digital Twin Image') {
            steps {
                sh '''
                trivy image ${DIGITAL_IMAGE}:${IMAGE_TAG}
                '''
            }
        }

        stage('Push Docker Images') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {

                    sh '''
                    echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin

                    docker push ${EXPENSE_IMAGE}:${IMAGE_TAG}
                    docker push ${EXPENSE_IMAGE}:latest

                    docker push ${DIGITAL_IMAGE}:${IMAGE_TAG}
                    docker push ${DIGITAL_IMAGE}:latest

                    docker logout
                    '''
                }
            }
        }

        stage('Cleanup Local Images') {
            steps {
                sh '''
                docker image rm ${EXPENSE_IMAGE}:${IMAGE_TAG} || true
                docker image rm ${EXPENSE_IMAGE}:latest || true

                docker image rm ${DIGITAL_IMAGE}:${IMAGE_TAG} || true
                docker image rm ${DIGITAL_IMAGE}:latest || true
                '''
            }
        }
    }

    post {

        always {
            archiveArtifacts artifacts: '*.txt', fingerprint: true
        }

        success {
            echo "=========================================="
            echo " DevSecOps CI Pipeline Completed Successfully "
            echo " Expense Tracker Image Pushed Successfully"
            echo " Digital Twin Image Pushed Successfully"
            echo "=========================================="
        }

        failure {
            echo "=========================================="
            echo " DevSecOps Pipeline Failed"
            echo " Check Console Output"
            echo "=========================================="
        }
    }
}
