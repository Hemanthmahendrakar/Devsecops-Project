pipeline {
    agent any

    environment {
        DOCKER_USERNAME = "hemanthkumarm3"

        EXPENSE_IMAGE = "hemanthkumarm3/expense-tracker"
        DIGITAL_IMAGE = "hemanthkumarm3/digital-twin"

        IMAGE_TAG = "${BUILD_NUMBER}"
    }

    tools {
        jdk 'jdk17'
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
                    waitForQualityGate abortPipeline: true
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
                    docker push ${DIGITAL_IMAGE}:${IMAGE_TAG}

                    docker logout
                    '''
                }
            }
        }

    }

    post {

        always {
            archiveArtifacts artifacts: '*.txt', fingerprint: true
        }

        success {
            echo 'CI Pipeline Completed Successfully'
        }

        failure {
            echo 'Pipeline Failed'
        }
    }
}
