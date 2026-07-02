pipeline {

    agent any

    environment {

        DOCKER_IMAGE = "hemanthkumarm3/devsecops-project"
        IMAGE_TAG = "${BUILD_NUMBER}"

    }

    stages {

        stage('Clone Repository') {
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
                sh 'trivy fs .'
            }
        }

        stage('Docker Build') {
            steps {

                sh """
                docker build -t ${DOCKER_IMAGE}:${IMAGE_TAG} .
                """

            }
        }

        stage('Trivy Image Scan') {
            steps {

                sh """
                trivy image ${DOCKER_IMAGE}:${IMAGE_TAG}
                """

            }
        }

        stage('Docker Login') {

            steps {

                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {

                    sh '''
                    echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin
                    '''

                }

            }

        }

        stage('Push Docker Image') {

            steps {

                sh """
                docker push ${DOCKER_IMAGE}:${IMAGE_TAG}
                """

            }

        }

    }

    post {

        success {

            echo "===================================="
            echo "Pipeline Executed Successfully"
            echo "===================================="

        }

        failure {

            echo "===================================="
            echo "Pipeline Failed"
            echo "===================================="

        }

    }

}
