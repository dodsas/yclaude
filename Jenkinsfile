pipeline {
  agent any

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  parameters {
    string(name: 'DEPLOY_HOST', defaultValue: 'dodsas.iptime.org', description: '배포 대상 서버 (호스트명 또는 IP)')
    string(name: 'DEPLOY_USER', defaultValue: 'dodsas', description: 'SSH 사용자')
    string(name: 'REMOTE_DIR', defaultValue: '/home/dodsas/work/ysclaude', description: '원격 작업 디렉토리')
    string(name: 'DEPLOY_BRANCH', defaultValue: 'main', description: '자동 배포 대상 브랜치')
  }

  environment {
    APP_NAME = 'ysclaude'
    SSH_CRED = 'ysadmin-deploy-ssh'
    // 관리자 대시보드 로그인 자격증명 (Jenkins Credentials: Username with password)
    ADMIN_CRED = 'ysclaude-admin'
    SSH_PORT = '22311'
    // HOST_PORT 는 운영 표준값으로 코드에 고정. Jenkins 파라미터 캐시 문제 회피.
    // 임시로 다른 포트로 띄울 일이 생기면 이 값만 바꾸고 커밋하거나, deploy.sh 를
    // 호스트에서 HOST_PORT=xxxx ./deploy.sh 직접 실행.
    HOST_PORT = '9091'
  }

  triggers {
    githubPush()
    pollSCM('H/2 * * * *')
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
        script {
          env.GIT_BRANCH_NAME = sh(returnStdout: true, script: "git rev-parse --abbrev-ref HEAD").trim()
          env.GIT_SHORT_SHA = sh(returnStdout: true, script: "git rev-parse --short HEAD").trim()
          env.IMAGE_TAG = "b${BUILD_NUMBER}-${env.GIT_SHORT_SHA}"
          echo "브랜치: ${env.GIT_BRANCH_NAME} / 이미지 태그: ${env.IMAGE_TAG}"
        }
      }
    }

    stage('Build & Deploy') {
      when {
        anyOf {
          expression { env.BRANCH_NAME == params.DEPLOY_BRANCH }
          expression { env.GIT_BRANCH_NAME == params.DEPLOY_BRANCH }
          expression { env.BRANCH_NAME == null && env.GIT_BRANCH_NAME == 'HEAD' }
        }
      }
      stages {
        stage('Package') {
          steps {
            sh '''
              set -e
              rm -f ${APP_NAME}.tar.gz
              git archive --format=tar.gz --output=${APP_NAME}.tar.gz HEAD
              ls -lh ${APP_NAME}.tar.gz
            '''
          }
        }

        stage('Transfer') {
          steps {
            withCredentials([sshUserPrivateKey(credentialsId: env.SSH_CRED, keyFileVariable: 'SSH_KEY')]) {
              sh '''
                set -e
                SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"
                ssh -p ${SSH_PORT} ${SSH_OPTS} ${DEPLOY_USER}@${DEPLOY_HOST} "mkdir -p ${REMOTE_DIR}"
                scp -P ${SSH_PORT} ${SSH_OPTS} ${APP_NAME}.tar.gz ${DEPLOY_USER}@${DEPLOY_HOST}:${REMOTE_DIR}/
                ssh -p ${SSH_PORT} ${SSH_OPTS} ${DEPLOY_USER}@${DEPLOY_HOST} "
                  set -e
                  cd ${REMOTE_DIR}
                  tar -xzf ${APP_NAME}.tar.gz
                  rm -f ${APP_NAME}.tar.gz
                  chmod +x deploy/*.sh
                "
              '''
            }
          }
        }

        stage('Deploy') {
          steps {
            withCredentials([
              sshUserPrivateKey(credentialsId: env.SSH_CRED, keyFileVariable: 'SSH_KEY'),
              usernamePassword(credentialsId: env.ADMIN_CRED, usernameVariable: 'ADMIN_USER', passwordVariable: 'ADMIN_PASSWORD')
            ]) {
              sh '''
                set -e
                SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"
                ssh -p ${SSH_PORT} ${SSH_OPTS} ${DEPLOY_USER}@${DEPLOY_HOST} "
                  export APP_NAME=${APP_NAME}
                  export APP_DIR=${REMOTE_DIR}
                  export HOST_PORT=${HOST_PORT}
                  export IMAGE_TAG=${IMAGE_TAG}
                  export ADMIN_USER='${ADMIN_USER}'
                  export ADMIN_PASSWORD='${ADMIN_PASSWORD}'
                  bash ${REMOTE_DIR}/deploy/deploy.sh
                "
              '''
            }
          }
        }

        stage('Smoke Test') {
          steps {
            withCredentials([sshUserPrivateKey(credentialsId: env.SSH_CRED, keyFileVariable: 'SSH_KEY')]) {
              sh '''
                set -e
                SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"
                ssh -p ${SSH_PORT} ${SSH_OPTS} ${DEPLOY_USER}@${DEPLOY_HOST} "
                  curl -fsS http://127.0.0.1:${HOST_PORT}/health
                "
              '''
            }
          }
        }
      }
    }
  }

  post {
    success {
      echo "✓ 배포 성공: http://${params.DEPLOY_HOST}:${params.HOST_PORT}  (image: localhost/ysclaude:${env.IMAGE_TAG})"
    }
    failure {
      echo "✗ 배포 실패. 콘솔 로그 확인 필요"
    }
    always {
      sh 'rm -f ${APP_NAME}.tar.gz || true'
    }
  }
}
