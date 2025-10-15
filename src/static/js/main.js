

        let evidenceDataCache = null; // 핵심 자료집 데이터를 캐싱할 변수

        // --- DOM Elements ---
        const loginScreen = document.getElementById('screen-login');
        const topicScreen = document.getElementById('screen-topic');
        const analysisScreen = document.getElementById('screen-analysis'); // 분석 화면 요소
        const juryScreen = document.getElementById('screen-jury');       // 배심원단 화면 요소
        const emailInput = document.getElementById('email-input');
        const passwordInput = document.getElementById('password-input');
        const loginButton = document.getElementById('login-button');
        const logoutButton = document.getElementById('logout-button');
        const loginError = document.getElementById('login-error');
        const userEmailDisplay = document.getElementById('user-email-display');
        const topicInput = document.getElementById('topic-input');
        const fileInput = document.getElementById('file-input');
        const fileNameDisplay = document.getElementById('file-name-display');
        const startAnalysisButton = document.getElementById('start-analysis-button');
        const juryContainer = document.getElementById('jury-container');

        // --- Global Variables ---
        let currentDiscussionId = null;     // 현재 토론 ID를 저장할 전역 변수
        let isPollingActive = false;        // 폴링 루프의 활성 상태를 관리
        let displayedMessagesCount = 0;     // 화면에 표시된 메시지 수 (전체)
        let regularMessageCount = 0;        // 일반 에이전트 메시지 카운터 (좌/우 정렬용)
        let isRendering = false;
        let isAutoScrollActive = true;      // 자동 스크롤 상태 변수 (기본값 ON)
        let userScrolledUp = false;         // 사용자가 수동으로 스크롤을 올렸는지 추적
        let scrollListenerAttached = false; // 스크롤 이벤트 리스너 중복 방지
        let discussionWorker; // 웹 워커 인스턴스를 저장할 변수
        let messageQueue = []; // [NEW] For Page Visibility API

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                console.log("[SmartScroll] Tab is visible again. Enabling auto-scroll and processing message queue.");
                // 브라우저 포커싱 시 자동 스크롤 재활성화 (요구사항 4)
                isAutoScrollActive = true;
                userScrolledUp = false;
                processMessageQueue();
                // 최신 메시지로 스크롤
                setTimeout(() => {
                    scrollToBottom(true);
                }, 100);
            }
        });

        /**
         * [스마트 스크롤] 채팅창을 최하단으로 스크롤합니다.
         * @param {boolean} force - true면 자동 스크롤 상태와 관계없이 강제 스크롤
         */
        function scrollToBottom(force = false) {
            const chatbox = document.getElementById('chatbox');
            if (!chatbox) return;

            if (force || isAutoScrollActive) {
                chatbox.scrollTop = chatbox.scrollHeight;
                console.log("[SmartScroll] Scrolled to bottom. Force:", force, "Auto:", isAutoScrollActive);
            }
        }

        /**
         * [스마트 스크롤] 자동 스크롤이 활성화된 경우에만 채팅창을 맨 아래로 내립니다.
         * @deprecated - scrollToBottom() 사용 권장
         */
        function scrollToBottomIfEnabled() {
            scrollToBottom(false);
        }

        /**
         * [스마트 스크롤] 요소가 최하단 근처에 있는지 확인합니다.
         * @param {HTMLElement} element - 확인할 요소
         * @param {number} threshold - 임계값 (픽셀)
         * @returns {boolean}
         */
        function isNearBottom(element, threshold = 50) {
            if (!element) return false;
            const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
            return distanceFromBottom <= threshold;
        }

        /**
         * [스마트 스크롤] 스크롤 이벤트 리스너를 초기화합니다.
         * 토론 화면으로 전환될 때 한 번만 호출되어야 합니다.
         */
        function initializeSmartScroll() {
            if (scrollListenerAttached) {
                console.log("[SmartScroll] Listener already attached. Skipping.");
                return;
            }

            const chatbox = document.getElementById('chatbox');
            if (!chatbox) {
                console.warn("[SmartScroll] Chatbox not found. Cannot initialize.");
                return;
            }

            // 사용자 스크롤 감지 (요구사항 2, 3)
            chatbox.addEventListener('scroll', () => {
                // 최하단 근처에 있으면 자동 스크롤 ON
                if (isNearBottom(chatbox, 50)) {
                    if (!isAutoScrollActive) {
                        console.log("[SmartScroll] User scrolled to bottom. Auto-scroll enabled.");
                    }
                    isAutoScrollActive = true;
                    userScrolledUp = false;
                } else {
                    // 사용자가 위로 스크롤하면 자동 스크롤 OFF
                    if (isAutoScrollActive) {
                        console.log("[SmartScroll] User scrolled up. Auto-scroll disabled.");
                    }
                    isAutoScrollActive = false;
                    userScrolledUp = true;
                }
            });

            scrollListenerAttached = true;
            console.log("[SmartScroll] Initialized successfully.");
        }

        // 지원 LLM 모델 목록 ---
        const SUPPORTED_MODELS = {
            "Google (Gemini)": [
                { id: "gemini-2.5-pro", name: "Gemini 2.5 pro" },
                { id: "gemini-2.5-flash", name: "Gemini 2.5 flash" }
            ],
            "OpenAI (GPT)": [
                /*
                { id: "gpt-5", name: "GPT-5" },
                { id: "gpt-5-mini", name: "GPT-5 mini" },
                { id: "gpt-5-nano", name: "GPT-5 nano" },
                 */
                { id: "gpt-4o", name: "GPT-4o" },
                { id: "gpt-4o-mini", name: "GPT-4o mini" },
                { id: "gpt-4-turbo", name: "GPT-4 Turbo" },
                { id: "gpt-4", name: "GPT-4" },
                { id: "gpt-3.5-turbo", name: "GPT-3.5 Turbo" }
            ],
            "Anthropic (Claude)": [
                { id: "claude-opus-4-1-20250805", name: "Claude 4.1 opus" },
                { id: "claude-opus-4-20250514", name: "Claude 4 Sonnet" },
                { id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku" },
                { id: "claude-3-7-sonnet-20250219", name: "Claude 3.7 Sonnet" },
                { id: "claude-3-5-sonnet-20241022", name: "Claude 3.5 Sonnet" },
                { id: "claude-3-haiku-20240307", name: "Claude 3 Haiku" }
            ]
        };
        
        
        // --- [NEW] Page Visibility & Rendering Functions ---
        function processMessageQueue() {
            if (document.hidden || isRendering || messageQueue.length === 0) {
                return;
            }
            isRendering = true;

            if (messageQueue.length > 1) {
                const latestData = messageQueue.pop(); 
                messageQueue = []; 
                renderTranscriptInstantly(latestData);
                isRendering = false; 
                processMessageQueue();
                return;
            }

            const dataToRender = messageQueue.shift();
            if (dataToRender) {
                renderTranscriptWithAnimation(dataToRender);
            } else {
                isRendering = false;
            }
        }

        function renderTranscriptInstantly(data) {
            console.log("Rendering discussion backlog instantly.");
            const chatbox = document.getElementById('chatbox');
            if (!chatbox) {
                isRendering = false;
                return;
            }

            const participantMap = getParticipantMap(data.participants);
            let html = '';
            let currentRegularCount = 0;
            const systemAgents = ['SNR 전문가', '정보 검증부', '사회자', '구분선'];

            data.transcript.forEach(turn => {
                if (systemAgents.includes(turn.agent_name)) {
                    html += createSystemMessageHtml(turn);
                } else {
                    html += createAgentMessageHtml(turn, participantMap, currentRegularCount);
                    currentRegularCount++;
                }
            });

            chatbox.innerHTML = html;
            regularMessageCount = currentRegularCount;
            displayedMessagesCount = data.transcript.length;
            
            renderUxPanels(data);
            checkDiscussionStatus(data);
            scrollToBottomIfEnabled();
        }

        function createAgentMessageHtml(turn, participantMap, count) {
            const agentDetails = participantMap[turn.agent_name] || {};
            const alignment = getAlignmentInfo(count);
            const iconHtml = `<div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">${agentDetails.icon || '🤖'}</div>`;
            const messageHtml = `
                <div class="flex flex-col ${alignment.isIconFirst ? '' : 'items-end'}">
                    <p class="text-sm font-bold text-slate-800">${turn.agent_name}</p>
                    <p class="text-xs text-slate-500 -mt-1">${getModelNameById(agentDetails.model || '')}</p>
                    <div class="p-3 rounded-lg mt-1 text-base inline-block max-w-xl ${alignment.bubbleClasses} ${alignment.textAlignClass}">
                         <span class="message-content">${markdownToHtml(turn.message)}</span>
                    </div>
                </div>`;
            return `<div class="${alignment.containerClasses}">${alignment.isIconFirst ? iconHtml + messageHtml : messageHtml + iconHtml}</div>`;
        }

        function createSystemMessageHtml(turn) {
            let contentHtml = '';
            if (turn.agent_name === 'SNR 전문가' || turn.agent_name === '정보 검증부') {
                const data = JSON.parse(turn.message);
                let icon = '';
                let colorClass = '';
                if (turn.agent_name === 'SNR 전문가') {
                    icon = '📈';
                    colorClass = 'text-blue-600';
                    contentHtml = `<strong>SNR Score:</strong> ${data.snr_score} - ${data.reason}`;
                } else {
                    icon = '✅';
                    colorClass = 'text-green-600';
                    if (data.status === '주의 필요') {
                        icon = '⚠️';
                        colorClass = 'text-orange-600';
                    }
                    contentHtml = `<strong>검증 상태:</strong> ${data.reason}`;
                }
                return `<div class="flex justify-center items-center gap-2 my-2 text-xs font-semibold animate-fade-in ${colorClass}">
                                 <span>${icon}</span>
                                 <span>[${turn.agent_name}]</span>
                                 <span>${contentHtml}</span>
                               </div>`;
            } else if (turn.agent_name === '사회자' || turn.agent_name === '재판관') {
                return `<div class="flex justify-center items-center gap-2 my-4 text-sm text-amber-800 animate-fade-in">
                                 <span class="text-xl">🧑</span>
                                 <span class="font-semibold">${turn.message}</span>
                               </div>`;
            } else if (turn.agent_name === '구분선') {
                return `<div class="text-center my-6 font-bold text-gray-400 animate-fade-in">${turn.message}</div>`;
            }
            return '';
        }

        function checkDiscussionStatus(data) {
            if (data.status === 'waiting_for_vote') {
                isPollingActive = false;
                renderUserActionPanel(data);
                if (discussionWorker) discussionWorker.postMessage({ command: 'stop' });
            } else if (data.status === 'completed') {
                console.log('[checkDiscussionStatus] "completed" status detected.');
                isPollingActive = false;
                displayReport(data.report_html, data.pdf_url);
                if (discussionWorker) discussionWorker.postMessage({ command: 'stop' });
            } else if (data.status === 'failed') {
                isPollingActive = false;
                document.getElementById('user-action-panel').innerHTML = `<div class="text-center p-4 border rounded-lg bg-red-50 border-red-400"><h3 class="text-xl font-bold text-red-800">❌ 처리 실패</h3><p class="text-slate-600 mt-2">오류가 발생했습니다. 관리자에게 문의하세요.</p></div>`;
                if (discussionWorker) discussionWorker.postMessage({ command: 'stop' });
            }
        }

        // --- Functions ---

        /**
         * 모델 ID를 사람이 읽을 수 있는 모델 이름으로 변환합니다.
         * @param {string} modelId - 변환할 모델의 ID
         * @returns {string} - 변환된 모델 이름 또는 ID (찾지 못한 경우)
         */
        function getModelNameById(modelId) {
            for (const provider in SUPPORTED_MODELS) {
                const foundModel = SUPPORTED_MODELS[provider].find(model => model.id === modelId);
                if (foundModel) {
                    return foundModel.name;
                }
            }
            return modelId; // 일치하는 이름을 찾지 못하면 ID를 그대로 반환
        }

        /**
         * 에이전트 정보와 LLM 목록을 기반으로 모델 선택 드롭다운 HTML을 생성합니다.
         * @param {object} agent - 에이전트 상세 정보 (name, model 포함)
         * @returns {string} - 생성된 <select> 태그의 HTML 문자열
         */
        function createModelSelector(agent) {
            let optionsHtml = '';
            for (const provider in SUPPORTED_MODELS) {
                optionsHtml += `<optgroup label="${provider}">`;
                SUPPORTED_MODELS[provider].forEach(model => {
                    // 현재 에이전트의 모델과 일치하는 옵션을 'selected'로 표시
                    const isSelected = model.id === agent.model ? 'selected' : '';
                    optionsHtml += `<option value="${model.id}" ${isSelected}>${model.name}</option>`;
                });
                optionsHtml += `</optgroup>`;
            }

            return `
                <select data-agent-name="${agent.name}" class="agent-model-selector w-full mt-1 p-1 border-gray-300 border rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                    ${optionsHtml}
                </select>
            `;
        }

        /**
         * JWT 토큰을 디코딩하여 payload 객체를 반환하는 함수
         * @param {string} token - JWT 액세스 토큰
         * @returns {object | null} - 디코딩된 payload 객체 또는 실패 시 null
         */
        function parseJwt(token) {
            try {
                const base64Url = token.split('.')[1];
                const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
                const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
                    return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
                }).join(''));

                return JSON.parse(jsonPayload);
            } catch (e) {
                console.error("JWT 파싱 실패:", e);
                return null;
            }
        }

        /**
         * 사용자가 스크롤을 맨 아래로 내렸는지 확인하는 헬퍼 함수
         * @param {HTMLElement} element - 확인할 DOM 요소
         * @returns {boolean} - 맨 아래에 있는지 여부
         */
        function isScrolledToBottom(element) {
            const buffer = 1; // 약간의 오차를 허용하는 버퍼
            return element.scrollHeight - element.scrollTop <= element.clientHeight + buffer;
        }

        // --- 정렬 관련 CSS 클래스를 반환하는 헬퍼 함수 ---
        function getAlignmentInfo(count) {
            const isOdd = count % 2 !== 0;
            if (isOdd) {
                // 오른쪽 정렬
                return {
                    containerClasses: 'flex gap-3 my-4 justify-end items-end',
                    bubbleClasses: 'bg-blue-500 text-white',
                    ttextAlignClass: 'text-left',
                    isIconFirst: false // 아이콘이 텍스트 뒤에 옴
                };
            } else {
                // 왼쪽 정렬
                return {
                    containerClasses: 'flex gap-3 my-4',
                    bubbleClasses: 'bg-slate-100',
                    textAlignClass: 'text-left',
                    isIconFirst: true // 아이콘이 텍스트 앞에 옴
                };
            }
        }
        
        /**
         * 화면을 전환하는 함수
         * @param {string} screenId - 표시할 화면의 ID
         */
        function showScreen(screenId) {
            document.querySelectorAll('.screen').forEach(screen => {
                screen.classList.remove('active');
            });
            document.getElementById(screenId).classList.add('active');

            // [스마트 스크롤] 실시간 토론 화면으로 전환 시 스크롤을 최하단으로
            if (screenId === 'screen-5') {
                setTimeout(() => {
                    scrollToBottom(true);
                }, 100);
            }
        }

        /**
         * 로그인 API를 호출하는 함수
         */
        async function handleLogin() {
            const email = emailInput.value;
            const password = passwordInput.value;
            const rememberMe = document.getElementById('remember-me-checkbox').checked; // 체크박스 상태 확인

            // 입력값 검증
            if (!email || !password) {
                loginError.textContent = '이메일과 비밀번호를 모두 입력해주세요.';
                return;
            }

            // 로딩 상태 표시
            loginButton.disabled = true;
            loginButton.textContent = '로그인 중...';
            loginError.textContent = '';

            // API는 x-www-form-urlencoded 형식을 요구하므로 FormData를 사용
            const formData = new URLSearchParams();
            formData.append('username', email);
            formData.append('password', password);

            try {
                const response = await fetch(`/api/v1/login/token`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: formData,
                });

                if (response.ok) {
                    const data = await response.json();
                    const token = data.access_token;

                    // JWT 토큰을 localStorage에 저장
                    localStorage.setItem('accessToken', data.access_token);
                    localStorage.setItem('userEmail', email);

                    if (rememberMe) {
                        localStorage.setItem('rememberedEmail', email);
                        localStorage.setItem('rememberedPassword', password); // 비밀번호 저장
                    } else {
                        localStorage.removeItem('rememberedEmail');
                        localStorage.removeItem('rememberedPassword'); // 비밀번호 삭제
                    }

                    // 로그인 성공 후 UI 업데이트 및 화면 전환
                    // 토큰 파싱 후 역할에 따라 분기 ---
                    const decodedToken = parseJwt(token);
                    if (decodedToken && decodedToken.role === 'admin') {
                        // 관리자일 경우, '/admin' 페이지로 리디렉션
                        console.log('관리자 로그인 성공. 관리자 페이지로 이동합니다.');
                        window.location.href = '/admin'; 
                    } else {
                        // 일반 사용자일 경우, 기존 로직대로 주제 입력 화면으로 전환
                        console.log('일반 사용자 로그인 성공:', data);
                        updateUIForLoggedInState();
                        showScreen('screen-topic');
                    }

                } else {
                    const errorData = await response.json();
                    loginError.textContent = errorData.detail || '로그인에 실패했습니다. 이메일 또는 비밀번호를 확인하세요.';
                    console.error('로그인 실패:', errorData);
                }
            } catch (error) {
                loginError.textContent = '서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.';
                console.error('네트워크 오류:', error);
            } finally {
                // 로딩 상태 해제
                loginButton.disabled = false;
                loginButton.textContent = '로그인';
            }
        }

        /**
         * 로그아웃 처리 함수
         */
        function handleLogout() {
            // 저장된 토큰과 이메일 정보 삭제
            localStorage.removeItem('accessToken');
            localStorage.removeItem('userEmail');
            
            console.log('로그아웃 되었습니다.');
            
            // UI 업데이트 및 로그인 화면으로 전환
            updateUIForLoggedOutState();
            showScreen('screen-login');
        }

        /**
         * '분석 시작' 버튼 클릭 시 오케스트레이션 파이프라인을 실행하는 함수
         */
        async function handleOrchestration() {
            const topic = topicInput.value.trim();
            const file = fileInput.files[0];
            const token = localStorage.getItem('accessToken');

            if (!topic) {
                alert('토론할 주제를 입력해주세요.');
                return;
            }
            if (!token) {
                alert('로그인이 필요합니다.');
                showScreen('screen-login');
                return;
            }

            showScreen('screen-analysis');
            updateAnalysisStep(1, '주제 분석 중...'); // 1단계 시작

            const formData = new FormData();
            formData.append('topic', topic);
            if (file) {
                formData.append('file', file);
            }

            try {
                // API 호출 시작 (백그라운드에서 오케스트레이션 진행)
                const response = await fetch('/api/v1/discussions/', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` },
                    body: formData,
                });

                if (response.status === 202) {
                    const data = await response.json();
                    console.log('Orchestration 백그라운드 시작:', data);

                    currentDiscussionId = data.discussion_id;
                    console.log('저장된 Discussion ID:', currentDiscussionId);

                    // 진행 상황 폴링 시작
                    startProgressPolling(currentDiscussionId, token);

                } else {
                    const errorData = await response.json();
                    alert(`분석 중 오류가 발생했습니다: ${errorData.detail}`);
                    showScreen('screen-topic');
                }
            } catch (error) {
                alert('서버에 연결할 수 없습니다.');
                showScreen('screen-topic');
                console.error('Orchestration 네트워크 오류:', error);
            }
        }

        /**
         * 진행 상황을 폴링하여 UI를 실시간으로 업데이트하는 함수
         */
        function startProgressPolling(discussionId, token) {
            let pollCount = 0;
            const maxPolls = 600; // 5분 타임아웃 (500ms * 600 = 300초)

            const intervalId = setInterval(async () => {
                pollCount++;

                // 타임아웃 체크
                if (pollCount > maxPolls) {
                    clearInterval(intervalId);
                    alert('진행 상황을 확인할 수 없습니다. 새로고침 후 다시 시도해주세요.');
                    showScreen('screen-topic');
                    return;
                }

                try {
                    const response = await fetch(`/api/v1/discussions/${discussionId}/progress`, {
                        headers: { 'Authorization': `Bearer ${token}` }
                    });

                    if (!response.ok) {
                        console.warn('진행 상황 조회 실패:', response.status);
                        return; // 다음 폴링에서 재시도
                    }

                    const progressData = await response.json();
                    console.log('진행 상황:', progressData);

                    // UI 업데이트
                    updateProgressUI(progressData);

                    // 100% 완료 시 폴링 중단 및 팀 정보 조회 후 화면 전환
                    if (progressData.progress >= 100) {
                        clearInterval(intervalId);

                        // DB에서 완성된 팀 정보 조회
                        try {
                            const detailResponse = await fetch(`/api/v1/discussions/${discussionId}`, {
                                headers: { 'Authorization': `Bearer ${token}` }
                            });

                            if (detailResponse.ok) {
                                const discussionDetail = await detailResponse.json();

                                // DebateTeam 형식으로 변환
                                const debateTeam = {
                                    discussion_id: discussionDetail.discussion_id,
                                    judge: discussionDetail.participants.find(p => p.name === '재판관'),
                                    jury: discussionDetail.participants.filter(p => p.name !== '재판관'),
                                    reason: "오케스트레이션 완료"
                                };

                                setTimeout(() => {
                                    renderJuryScreen(debateTeam);
                                    showScreen('screen-jury');
                                }, 1500); // 사용자가 완료 메시지를 볼 수 있도록 1.5초 대기
                            } else {
                                throw new Error('팀 정보 조회 실패');
                            }
                        } catch (err) {
                            console.error('팀 정보 조회 오류:', err);
                            alert('토론 팀 정보를 불러올 수 없습니다.');
                            showScreen('screen-topic');
                        }
                    }

                } catch (error) {
                    console.error('진행 상황 폴링 오류:', error);
                    // 에러가 발생해도 계속 폴링 (일시적인 네트워크 오류일 수 있음)
                }
            }, 500); // 500ms마다 폴링
        }

        /**
         * Redis에서 받은 진행 상황 데이터로 UI를 업데이트하는 함수
         */
        function updateProgressUI(progressData) {
            const progressBar = document.getElementById('progress-bar');
            const analysisStatusText = document.getElementById('analysis-status-text');
            const detailProgressText = document.getElementById('detail-progress-text');

            // 프로그레스 바 업데이트
            progressBar.style.width = progressData.progress + '%';

            // 상태 메시지 업데이트 (큰 제목)
            if (progressData.stage) {
                analysisStatusText.textContent = `[${progressData.stage}] ${progressData.message}`;
            } else {
                analysisStatusText.textContent = progressData.message;
            }

            // 상세 메시지 업데이트 (파란색 박스)
            detailProgressText.textContent = progressData.message;

            // 단계별 UI 업데이트
            if (progressData.progress >= 10 && progressData.progress < 35) {
                // 1단계: 주제 분석
                document.getElementById('step-1-status').textContent = '진행 중';
            } else if (progressData.progress >= 35 && progressData.progress < 75) {
                // 2단계: 자료 수집
                const step2Div = document.getElementById('step-2');
                step2Div.classList.remove('opacity-50');
                step2Div.querySelector('div').className = 'w-12 h-12 rounded-full bg-blue-500 text-white flex items-center justify-center mx-auto font-bold text-xl ring-4 ring-white';
                const step2Text = step2Div.querySelector('p.text-slate-400');
                if (step2Text) step2Text.classList.remove('text-slate-400');
                document.getElementById('step-1-status').textContent = '완료';
                document.getElementById('step-2-status').textContent = '진행 중';
            } else if (progressData.progress >= 75) {
                // 3단계: 전문가 선정
                const step3Div = document.getElementById('step-3');
                step3Div.classList.remove('opacity-50');
                step3Div.querySelector('div').className = 'w-12 h-12 rounded-full bg-blue-500 text-white flex items-center justify-center mx-auto font-bold text-xl ring-4 ring-white';
                const step3Text = step3Div.querySelector('p.text-slate-400');
                if (step3Text) step3Text.classList.remove('text-slate-400');
                document.getElementById('step-2-status').textContent = '완료';
                document.getElementById('step-3-status').textContent = '진행 중';

                if (progressData.progress === 100) {
                    document.getElementById('step-3-status').textContent = '완료';
                }
            }
        }

        // 분석 단계별 UI 업데이트를 위한 헬퍼 함수
        function updateAnalysisStep(stepNumber, statusText) {
            const progressBar = document.getElementById('progress-bar');
            const analysisStatusText = document.getElementById('analysis-status-text');
            
            analysisStatusText.textContent = statusText;

            if (stepNumber === 1) {
                progressBar.style.width = '15%';
            } else if (stepNumber === 2) {
                progressBar.style.width = '50%';
                const step2Div = document.getElementById('step-2');
                step2Div.classList.remove('opacity-50');
                step2Div.querySelector('div').className = 'w-12 h-12 rounded-full bg-blue-500 text-white flex items-center justify-center mx-auto font-bold text-xl ring-4 ring-white';
                document.getElementById('step-1-status').textContent = '완료';
                document.getElementById('step-2-status').textContent = '진행 중';
            } else if (stepNumber === 3) {
                progressBar.style.width = '100%';
                const step3Div = document.getElementById('step-3');
                step3Div.classList.remove('opacity-50');
                step3Div.querySelector('div').className = 'w-12 h-12 rounded-full bg-blue-500 text-white flex items-center justify-center mx-auto font-bold text-xl ring-4 ring-white';
                document.getElementById('step-2-status').textContent = '완료';
                document.getElementById('step-3-status').textContent = '진행 중';
            }
        }

        /**
         * 분석 과정 3단계 애니메이션을 시뮬레이션하는 함수
         */
        /*
        function runAnalysisAnimation() {
            // UI 요소 가져오기
            const progressBar = document.getElementById('progress-bar');
            const analysisStatusText = document.getElementById('analysis-status-text');
            const steps = {
                1: { div: document.getElementById('step-1'), status: document.getElementById('step-1-status') },
                2: { div: document.getElementById('step-2'), status: document.getElementById('step-2-status') },
                3: { div: document.getElementById('step-3'), status: document.getElementById('step-3-status') }
            };

            // 2단계 진행
            setTimeout(() => {
                progressBar.style.width = '50%';
                analysisStatusText.textContent = '웹 검색 및 파일 분석 중...';
                steps[1].status.textContent = '완료';
                steps[2].div.classList.remove('opacity-50');
                steps[2].div.querySelector('div').className = 'w-12 h-12 rounded-full bg-blue-500 text-white flex items-center justify-center mx-auto font-bold text-xl ring-4 ring-white';
                steps[2].status.textContent = '자료 확보 중';
            }, 1500); // 1.5초 후

            // 3단계 진행
            setTimeout(() => {
                progressBar.style.width = '100%';
                analysisStatusText.textContent = '최적의 전문가 팀 구성 중...';
                steps[2].status.textContent = '완료';
                steps[3].div.classList.remove('opacity-50');
                steps[3].div.querySelector('div').className = 'w-12 h-12 rounded-full bg-blue-500 text-white flex items-center justify-center mx-auto font-bold text-xl ring-4 ring-white';
                steps[3].status.textContent = '선발 중';
            }, 3000); // 3초 후
        }
        */

        /**
         * API 응답 데이터를 기반으로 배심원단 확인 화면을 동적으로 생성하는 함수
         * @param {object} teamData - /orchestrate API의 응답 데이터 (DebateTeam)
         */
        function renderJuryScreen(teamData) {
            const iconMap = { 
                "사회자": "🧑‍⚖️", "거시경제 전문가": "🌍", "산업 분석가": "🏭", 
                "재무 분석가": "💹", "SNS 트렌드 분석가": "📱", "비판적 관점": "🤔", 
                "워렌 버핏": "👴", "피터 린치": "👨‍💼", "스티브 잡스": "💡", 
                "일론 머스크": "🚀", "심리학 전문가": "🧠", "미래학자": "🔭", "IT 전문가": "💻" 
            };
            
            let juryHtml = '';
            teamData.jury.forEach(agent => {
                const icon = agent.icon || iconMap[agent.name] || '🤖';
                const modelSelectorHtml = createModelSelector(agent); 
                
                juryHtml += `
                    <div class="flex flex-col items-center text-center p-3 bg-white rounded-lg shadow-sm">
                        <span class="text-3xl">${icon}</span>
                        <p class="font-bold mt-2">${agent.name}</p>
                        ${modelSelectorHtml}
                    </div>`;
            });

            const judgeName = teamData.judge.name;
            const judgeIcon = teamData.judge.icon || iconMap[judgeName] || '🧑';
            
            const fullHtml = `
                <div class="text-center mb-8">
                    <h2 class="text-2xl font-bold text-slate-800">전문가 에이전트 구성이 완료되었습니다.</h2>
                    <p class="text-slate-600 mt-2">각 전문가가 사용할 LLM을 변경할 수 있습니다. 준비가 되면 토론을 시작하세요.</p>
                </div>
                <div class="mb-8">
                    <div class="bg-amber-50 border-2 border-amber-400 p-4 rounded-xl flex flex-col sm:flex-row items-center gap-4">
                        <span class="text-5xl">${judgeIcon}</span>
                        <div class="text-center sm:text-left flex-grow">
                            <h3 class="text-lg font-bold text-amber-800">사회자</h3>
                            <p class="text-sm text-slate-600 mt-1">${teamData.judge.model}</p>
                        </div>
                    </div>
                </div>
                <div class="border-2 border-slate-200 bg-slate-50 p-6 rounded-xl">
                    <h3 class="font-bold text-slate-700 text-center mb-4 text-lg">AI 전문가 에이전트</h3>
                    <p class="text-center text-sm text-slate-500 mb-4">${teamData.reason}</p>
                    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">${juryHtml}</div>
                </div>
                <button id="start-debate-btn" class="btn btn-primary w-full mt-8">이 구성으로 토론 시작하기</button>
            `;
            juryContainer.innerHTML = fullHtml;
            
            document.getElementById('start-debate-btn').addEventListener('click', startDebate);
        }

        /**
         * 모달창을 토글하는 헬퍼 함수
         */
        function toggleModal(modalId) {
            const modal = document.getElementById(modalId);
            if (modal.classList.contains('hidden')) {
                modal.classList.remove('hidden');
                setTimeout(() => modal.classList.remove('opacity-0'), 10);
            } else {
                modal.classList.add('opacity-0');
                setTimeout(() => modal.classList.add('hidden'), 300);
            }
        }

        /**
         * '핵심 자료집 보기' 버튼 클릭 시 실행되는 함수
         */
        async function showEvidenceModal() {
            // 이미 데이터를 불러왔으면 캐시된 데이터로 모달을 즉시 표시
            if (evidenceDataCache) {
                renderEvidenceModal(evidenceDataCache);
                toggleModal('evidence-modal');
                return;
            }

            // 데이터를 처음 불러오는 경우
            if (!currentDiscussionId) {
                alert("오류: 현재 토론 ID를 찾을 수 없습니다.");
                return;
            }
            const token = localStorage.getItem('accessToken');
            
            try {
                const response = await fetch(`/api/v1/discussions/${currentDiscussionId}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (!response.ok) throw new Error('Failed to fetch discussion details.');
                
                const discussionData = await response.json();
                evidenceDataCache = discussionData.evidence_briefing; // 결과 캐싱
                
                renderEvidenceModal(evidenceDataCache);
                toggleModal('evidence-modal');

            } catch (error) {
                console.error("Error fetching evidence data:", error);
                document.getElementById('evidence-modal-body').innerHTML = '<p>데이터를 불러오는 데 실패했습니다.</p>';
                toggleModal('evidence-modal');
            }
        }

        /**
         * 받아온 데이터로 모달 내용을 채우는 함수
         */
        function renderEvidenceModal(data) {
            const container = document.getElementById('evidence-modal-body');
            if (!data) {
                container.innerHTML = '<p>핵심 자료집 데이터가 없습니다.</p>';
                return;
            }

            // URL 유효성 검사 및 <a> 태그 생성 헬퍼 함수
            function formatSource(source) {
                // 간단한 URL 형식 검사 (http/https로 시작하는지)
                if (source.startsWith('http://') || source.startsWith('https://')) {
                    return `<a href="${source}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:underline break-word-container">${source}</a>`;
                }
                return `<span class="break-word-container">${source}</span>`;
            }

            const webHtml = data.web_evidence && data.web_evidence.length > 0
                ? data.web_evidence.map(item => `
                    <div class="mb-3 p-3 border border-gray-200 rounded-md bg-white shadow-sm">
                        <p class="font-semibold text-gray-700 mb-1">출처: ${formatSource(item.source)}</p>
                        <p class="text-gray-800">${item.summary}</p>
                        <p class="text-sm text-gray-500 mt-1">발행일: ${item.publication_date || '알 수 없음'}</p>
                    </div>
                `).join('')
                : '<p class="text-gray-600">관련 웹 검색 결과가 없습니다.</p>';

            const fileHtml = data.file_evidence && data.file_evidence.length > 0
                ? data.file_evidence.map(item => `
                    <div class="mb-3 p-3 border border-gray-200 rounded-md bg-white shadow-sm">
                        <p class="font-semibold text-gray-700 mb-1">첨부 파일: <span class="break-word-container">${item.source}</span></p>
                        <p class="text-gray-800">${item.summary}</p>
                        <p class="text-sm text-gray-500 mt-1">확인일: ${item.publication_date || '알 수 없음'}</p>
                    </div>
                `).join('')
                : '<p class="text-gray-600">첨부된 파일이 없습니다.</p>';

            container.innerHTML = `
                <div class="mb-6">
                    <h3 class="font-bold text-lg mb-3 text-primary-dark">🌐 웹 검색 결과 요약</h3>
                    <div class="bg-gray-50 p-4 rounded-lg shadow-inner space-y-4">${webHtml}</div>
                </div>
                <div>
                    <h3 class="font-bold text-lg mb-3 text-primary-dark">📁 사용자 첨부 파일 요약</h3>
                    <div class="bg-gray-50 p-4 rounded-lg shadow-inner space-y-4">${fileHtml}</div>
                </div>
            `;
        }

        /**
         * '토론 시작하기' 버튼 클릭 시, 백엔드에 토론 실행을 요청하는 함수
         */
        async function startDebate() {

            if (!currentDiscussionId) {
                alert('오류: 토론 ID를 찾을 수 없습니다.');
                return;
            }

            const token = localStorage.getItem('accessToken');
            const startDebateBtn = document.getElementById('start-debate-btn');

            // 로딩 상태 표시
            startDebateBtn.disabled = true;
            startDebateBtn.textContent = '토론을 준비 중입니다...';

            // 각 에이전트별로 선택된 모델 값을 읽어옵니다. ---
            const modelOverrides = {};
            document.querySelectorAll('.agent-model-selector').forEach(selector => {
                const agentName = selector.dataset.agentName;
                const selectedModel = selector.value;
                if (agentName && selectedModel) {
                    modelOverrides[agentName] = selectedModel;
                }
            });
            console.log("사용자가 선택한 모델 구성:", modelOverrides);

            try {
                const response = await fetch(`/api/v1/discussions/${currentDiscussionId}/turns`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    },
                    // body에 사용자가 선택한 모델 정보를 포함하여 전송합니다.
                    body: JSON.stringify({ 
                        user_vote: null, // 첫 턴이므로 user_vote는 null 입니다.
                        model_overrides: modelOverrides 
                    })
                });

                if (response.status === 202) { // 202 Accepted
                    console.log('백그라운드 토론 작업이 성공적으로 시작되었습니다.');

                    resetDiscussionUI();

                    displayedMessagesCount = 0; // 새 토론 시작 시 카운트 초기화
                    regularMessageCount = 0;    // 일반 메시지 카운트 초기화
                    const chatbox = document.getElementById('chatbox');
                    chatbox.innerHTML = '<div id="waiting-message" class="text-center text-slate-500">AI 에이전트들의 발언을 기다리고 있습니다...</div>'; // 초기 메시지 설정
                    // 다음 단계: 실시간 토론 화면으로 전환
                    showScreen('screen-5'); 

                    // 채팅창을 비우는 대신, 범용 "입력 중" 인디케이터를 표시합니다.
                    showGeneralTypingIndicator(true); 

                    startPolling(currentDiscussionId); // 폴링 시작

                    // '핵심 자료집 보기' 버튼에 이벤트 리스너 연결
                    const evidenceBtn = document.getElementById('view-evidence-btn');
                    evidenceBtn.addEventListener('click', showEvidenceModal);
                } else {
                    const errorData = await response.json();
                    alert(`토론 시작에 실패했습니다: ${errorData.detail}`);
                    startDebateBtn.disabled = false;
                    startDebateBtn.textContent = '이 구성으로 토론 시작하기';
                }
            } catch (error) {
                alert('서버 연결에 실패했습니다.');
                console.error('토론 시작 API 호출 오류:', error);
                startDebateBtn.disabled = false;
                startDebateBtn.textContent = '이 구성으로 토론 시작하기';
            }
        }




        /**
         * 웹 워커를 사용하여 주기적으로 토론 상태를 요청하는 함수
         */
        function startPolling(discussionId) {
            if (isPollingActive) {
                return;
            }
            isPollingActive = true;
            messageQueue = []; // Clear queue for new discussion
            
            if (discussionWorker) {
                discussionWorker.terminate();
            }

            discussionWorker = new Worker('/tools/worker.js');

            discussionWorker.onmessage = function(e) {
                console.log('[Worker Data Received]', e.data); // Log all received data

                // [HIGH PRIORITY] Check for final 'completed' status and process immediately
                if (e.data.type === 'data' && e.data.data.status === 'completed') {
                    console.log('[High Priority] "completed" status received. Bypassing queue and rendering report directly.');
                    checkDiscussionStatus(e.data.data);
                    return; // Stop further processing of this message
                }

                const { type, data, error, status } = e.data;

                if (type === 'data') {
                    messageQueue.push(data);
                    processMessageQueue();
                } else if (type === 'error') {
                    console.error('Worker error:', error);
                    isPollingActive = false;
                } else if (type === 'status') {
                    console.log(`Worker status: ${status}`);
                }
            };

            discussionWorker.onerror = function(e) {
                console.error('Worker error event:', e);
                isPollingActive = false;
            };

            const token = localStorage.getItem('accessToken');
            discussionWorker.postMessage({
                command: 'start',
                data: { discussionId, token }
            });
        }

        // 기존 pollDiscussionStatus 함수는 이제 워커가 담당하므로 삭제하거나 주석 처리합니다.
        /*
         async function pollDiscussionStatus(discussionId) { ... }
        */

        /**
        * 보고서와 PDF 다운로드 버튼을 화면에 표시하는 함수
        */
        function displayReport(reportHtml, pdfUrl) {
            console.log('[displayReport] Function called with reportHtml length:', reportHtml ? reportHtml.length : 0, 'and pdfUrl:', pdfUrl);
            const actionPanel = document.getElementById('user-action-panel');
            if (!actionPanel) return;

            actionPanel.innerHTML = `
                <div class="text-center p-4 border rounded-lg bg-green-50 border-green-500 animate-fade-in">
                    <button id="view-report-btn" class="btn btn-primary w-full">✅ 최종 분석 보고서 보기</button>
                </div>
            `;
            
            const iframe = document.getElementById('report-modal-iframe');
            const downloadBtn = document.getElementById('report-pdf-download-btn');
            
            if (iframe) {
                iframe.sandbox = 'allow-scripts allow-same-origin';
                iframe.srcdoc = reportHtml || '<p>보고서 내용이 없습니다.</p>';
            }
            if (downloadBtn) {
                downloadBtn.href = pdfUrl || '#';
                downloadBtn.disabled = !pdfUrl;
                if (!pdfUrl) {
                    downloadBtn.classList.add('bg-slate-400', 'cursor-not-allowed');
                }
            }
            
            document.getElementById('view-report-btn').addEventListener('click', () => {
                toggleModal('report-modal');
            });
        }


        /**
         * 모든 UX 패널의 렌더링을 관리하는 함수!
         */
        function renderUxPanels(data) {
            if (data.round_summary) {
                renderCriticalUtterance(data.round_summary.critical_utterance);
                renderStanceChanges(data.round_summary.stance_changes, data.participants);
            }
            if (data.flow_data) {
                renderFlowDiagram(data.flow_data.interactions, data.participants);
            }
        }

        /**
         * '결정적 발언' 패널을 렌더링하는 함수
         */
        function renderCriticalUtterance(utterance) {
            const panel = document.getElementById('critical-hit-panel'); // UI에 해당 ID가 있어야 함
            if (!panel || !utterance) return;
            panel.innerHTML = `
                <h3 class="font-bold text-yellow-800 text-lg mb-2">⚡ 결정적 발언</h3>
                <div class="text-sm text-slate-700">
                    <p class="font-semibold">[${utterance.agent_name}]</p>
                    <p class="mt-1">"${utterance.message}"</p>
                </div>`;
        }

        /**
         * '에이전트 입장 변화' 패널을 렌더링하는 함수
         */
        function renderStanceChanges(stanceChanges, participants) {
            const panel = document.getElementById('stance-tracker');
            if (!panel) return;

            // [수정] stanceChanges 데이터가 없거나 비어있을 경우 초기 메시지 표시
            if (!stanceChanges || stanceChanges.length === 0) {
                panel.innerHTML = '<p class="text-sm text-slate-500 text-center">다음 라운드부터 입장 변화가 표시됩니다.</p>';
                return;
            }

            const participantMap = getParticipantMap(participants);
            let html = '';
            stanceChanges.forEach(change => {
                html += `
                    <div class="flex items-center justify-between text-sm">
                        <div class="flex items-center gap-2">
                            <span class="text-xl">${participantMap[change.agent_name]?.icon || '🤖'}</span>
                            <span class="font-semibold">${change.agent_name}</span>
                        </div>
                        <div class="font-bold flex items-center gap-1.5">
                        ${change.icon} ${change.change}
                        </div>
                    </div>`;
            });
            panel.innerHTML = html;
        }

        /**
         * 상호작용을 단순한 목록 형태로 렌더링하는 함수
         */
        function renderInteractionList(interactions, participants) {
            const container = document.getElementById('flow-diagram-container');
            
            // 로그는 유지하여 데이터 수신 여부 계속 확인
            console.log('%c[Flow Diagram] 1. Rendering list view.', 'color: blue; font-weight: bold;', {
                'Received Interactions': interactions
            });

            if (!container) {
                console.error('[Flow Diagram] Error: Container element not found!');
                return;
            }

            // 상호작용 데이터가 없는 경우 메시지 표시
            if (!interactions || interactions.length === 0) {
                container.innerHTML = '<p class="text-sm text-center text-slate-500">이번 라운드에서는 에이전트 간의 직접적인 상호작용이 감지되지 않았습니다.</p>';
                container.style.height = 'auto';
                return;
            }

            const participantMap = getParticipantMap(participants);
            container.style.height = 'auto'; // 컨테이너 높이를 내용에 맞게 자동 조절

            // 각 상호작용에 대한 HTML 행(row)을 생성
            const interactionRowsHtml = interactions.map(flow => {
                const fromAgent = participantMap[flow.from] || { icon: '🤖' };
                const toAgent = participantMap[flow.to] || { icon: '🤖' };
                
                // 상호작용 유형(agreement/disagreement)에 따라 화살표 색상 결정
                const arrowClass = flow.type === 'agreement' ? 'arrow-agreement' : 'arrow-disagreement';

                return `
                    <div class="flow-list-item">
                        <div class="flow-agent-box from">
                            <div class="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-xl flex-shrink-0">${fromAgent.icon}</div>
                            <span class="text-xs font-bold truncate">${flow.from}</span>
                        </div>

                        <div class="flow-arrow">
                            <svg class="${arrowClass}" viewBox="0 0 100 16" preserveAspectRatio="none"><path d="M0,8 L100,8 M90,2 L100,8 L90,14" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        </div>

                        <div class="flow-agent-box to">
                            <span class="text-xs font-bold truncate">${flow.to}</span>
                            <div class="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-xl flex-shrink-0">${toAgent.icon}</div>
                        </div>
                    </div>
                `;
            }).join('');

            container.innerHTML = `<div class="w-full">${interactionRowsHtml}</div>`;
        }

        /**
         * '토론 흐름도' 패널을 렌더링하는 함수
         */
        function renderFlowDiagram(interactions, participants) {
            renderInteractionList(interactions, participants);
        }

        /**
         * 토론 흐름도 화살표를 그리는 헬퍼 함수
         */
        /**
         * 두 HTML 요소(el1, el2)를 연결하는 화살표 선(div)을 생성하여 반환합니다.
         * @param {HTMLElement} el1 - 시작 요소
         * @param {HTMLElement} el2 - 도착 요소
         * @returns {HTMLElement} - 스타일이 적용된 화살표 선 div 요소
         */
        /**
         * 두 HTML 요소를 연결하는 화살표 선을 생성하는 안정화된 함수
         * getBoundingClientRect() 대신 offsetLeft/Top을 사용하여 위치 계산의 정확성을 높입니다.
         */
        function createFlowLine(el1, el2, colorClass) {
            // 1. 각 에이전트 노드(el1, el2) 내부의 아이콘 div를 직접 참조합니다.
            const icon1 = el1.querySelector('div:first-child');
            const icon2 = el2.querySelector('div:first-child');

            // 2. offset 속성을 사용하여 부모 컨테이너 내에서의 상대적 위치를 계산합니다.
            // el.offsetLeft: 부모로부터의 가로 이격 거리
            // icon.offsetWidth: 아이콘 자체의 너비
            const x1 = el1.offsetLeft + icon1.offsetWidth / 2;
            const y1 = el1.offsetTop + icon1.offsetHeight / 2;
            const x2 = el2.offsetLeft + icon2.offsetWidth / 2;
            const y2 = el2.offsetTop + icon2.offsetHeight / 2;

            // 3. 두 점 사이의 거리(화살표 길이)와 각도 계산
            const length = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
            const angle = Math.atan2(y2 - y1, x2 - x1) * (180 / Math.PI);

            // 4. 계산된 값을 바탕으로 화살표 DOM 요소를 생성
            const line = document.createElement('div');
            line.className = `flow-line ${colorClass}`;
            line.style.width = `${length}px`;
            line.style.left = `${x1}px`;
            line.style.top = `${y1}px`;
            line.style.transform = `rotate(${angle}deg)`;
            
            return line;
        }

        /**
         * 사용자 액션 패널(투표, 다음 행동 버튼)을 렌더링하는 함수
         */
        function renderUserActionPanel(discussionData) {
            const actionPanel = document.getElementById('user-action-panel');
            if (!actionPanel) {
                console.error("[로그 오류] 'user-action-panel' 요소를 찾을 수 없습니다.");
                return;
            }

            /* [임시 비활성화] 투표 기능 UI 렌더링 로직
            const voteData = discussionData.current_vote;
            
            // 렌더링 조건 검사 강화 및 로그 추가
            if (voteData && voteData.topic && Array.isArray(voteData.options) && voteData.options.length > 0) {
                console.log('%c[로그 성공] 투표 데이터가 유효하여 투표 UI를 렌더링합니다.', 'color: green');
                let optionsHtml = '';
                voteData.options.forEach(option => {
                    const optionText = String(option);
                    optionsHtml += `<button class="btn btn-subtle vote-option" data-vote="${optionText}">${optionText}</button>`;
                });
                actionPanel.innerHTML = `
                    <div class="bg-amber-100 border-l-4 border-amber-500 p-4 rounded-r-lg shadow-lg animate-fade-in">
                        <p class="font-bold text-amber-800">사회자의 투표 제안 (Round ${discussionData.turn_number})</p>
                        <p class="mt-2 text-base text-amber-900">"${voteData.topic}"</p>
                        <div id="vote-options-container" class="flex flex-wrap gap-3 justify-center mt-4">
                            ${optionsHtml}
                        </div>
                    </div>
                    <div class="flex justify-center gap-4 mt-6">
                        <button id="next-round-btn" class="btn btn-primary">다음 라운드 진행</button>
                        <button id="end-debate-report-btn" class="btn btn-secondary">보고서 생성하고 종료</button>
                        <button id="end-debate-no-report-btn" class="btn bg-slate-600 text-white hover:bg-slate-700">보고서 없이 종료</button>
                    </div>
                `;
            } else {
                console.warn('%c[로그 경고] 투표 데이터가 유효하지 않아 기본 버튼을 렌더링합니다.', 'color: orange');
                actionPanel.innerHTML = `
                    <div class="flex justify-center gap-4 mt-6">
                        <button id="next-round-btn" class="btn btn-primary">다음 라운드 진행</button>
                        <button id="end-debate-btn" class="btn btn-secondary">이대로 토론 종료</button>
                    </div>`;
            }
            */

            // [수정] 투표 기능 비활성화를 위해 항상 진행/종료 버튼만 표시
            actionPanel.innerHTML = `
                <div class="flex justify-center gap-4 mt-6">
                    <button id="next-round-btn" class="btn btn-primary">다음 라운드 진행</button>
                    <button id="end-debate-report-btn" class="btn btn-secondary">보고서 생성하고 종료</button>
                    <button id="end-debate-no-report-btn" class="btn bg-slate-600 text-white hover:bg-slate-700">보고서 없이 종료</button>
                </div>
            `;

            // 이벤트 리스너 연결
            document.getElementById('next-round-btn').addEventListener('click', handleNextRound);
            document.getElementById('end-debate-report-btn').addEventListener('click', handleEndDebate); // 보고서 생성
            document.getElementById('end-debate-no-report-btn').addEventListener('click', handleEndDebateWithoutReport); // 보고서 없이 종료
            
            /* [임시 비활성화] 투표 옵션 컨테이너 이벤트 리스너
            const voteOptionsContainer = document.getElementById('vote-options-container');
            if (voteOptionsContainer) {
                voteOptionsContainer.addEventListener('click', (event) => {
                    if (event.target.classList.contains('vote-option')) {
                        voteOptionsContainer.querySelectorAll('.vote-option').forEach(btn => {
                            btn.classList.remove('bg-blue-600', 'text-white');
                        });
                        event.target.classList.add('bg-blue-600', 'text-white');
                    }
                });
            }
            */
        }

        /**
         * '다음 라운드 진행' 버튼의 로직을 처리하는 함수
         */
        async function handleNextRound() {
            const nextRoundBtn = document.getElementById('next-round-btn');
            nextRoundBtn.disabled = true;
            nextRoundBtn.textContent = '다음 라운드를 준비 중입니다...';

            const selectedOption = document.querySelector('.vote-option.bg-blue-600');
            const userVote = selectedOption ? selectedOption.dataset.vote : null;
            
            /* [임시 비활성화] 투표를 선택하지 않았을 경우의 확인창 로직
            if (userVote === null) {
                if (!confirm("투표 항목을 선택하지 않았습니다. 그대로 다음 라운드를 진행할까요?")) {
                    return; // 사용자가 '취소'를 누르면 함수 실행 중단
                }
            }
            */

            const token = localStorage.getItem('accessToken');
            try {
                const response = await fetch(`/api/v1/discussions/${currentDiscussionId}/turns`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ user_vote: userVote })
                });

                if (response.status === 202) {
                    document.getElementById('user-action-panel').innerHTML = ''; // 액션 패널 비우기

                    // 다음 라운드를 위해 범용 "입력 중" 인디케이터를 다시 표시합니다.
                    showGeneralTypingIndicator(true);

                    startPolling(currentDiscussionId); // 다음 라운드를 위해 폴링 다시 시작
                } else {
                    const errorData = await response.json();
                    alert(`다음 라운드 시작에 실패했습니다: ${errorData.detail}`);
                    nextRoundBtn.disabled = false;
                    nextRoundBtn.textContent = '다음 라운드 진행';
                }
            } catch (error) {
                alert('서버 연결에 실패했습니다.');
                nextRoundBtn.disabled = false;
                nextRoundBtn.textContent = '다음 라운드 진행';
            }
        }

        /**
         * '토론 종료' 버튼의 로직을 처리하는 함수
         */
        async function handleEndDebate() {
            console.log("토론 종료 및 보고서 생성 프로세스를 시작합니다.");
            isPollingActive = false; // 진행 중인 턴 폴링 즉시 중단

            const actionPanel = document.getElementById('user-action-panel');
            actionPanel.innerHTML = `
                <div class="text-center p-4 border rounded-lg bg-slate-50 animate-fade-in">
                    <div class="flex items-center justify-center">
                        <div class="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-blue-500 mr-3"></div>
                        <p class="text-slate-600 font-semibold">최종 보고서 생성 중... 완료되면 버튼이 활성화됩니다.</p>
                    </div>
                </div>
            `;
            
            if (!currentDiscussionId) {
                alert("오류: 토론 ID가 없어 보고서를 생성할 수 없습니다.");
                showScreen('screen-topic');
                return;
            }

            const token = localStorage.getItem('accessToken');
            try {
                // 백엔드에 토론 완료 및 보고서 생성 시작을 알리는 API 호출
                const response = await fetch(`/api/v1/discussions/${currentDiscussionId}/complete`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.status === 202) {
                    console.log("서버가 보고서 생성 요청을 성공적으로 접수했습니다.");
                    // 보고서 완성을 확인하기 위한 새로운 폴링 시작
                    startPolling(currentDiscussionId);
                } else {
                    const errorData = await response.json();
                    alert("보고서 생성 시작에 실패했습니다: " + errorData.detail);
                    actionPanel.innerHTML = `<div class="text-center p-4 border rounded-lg bg-red-50 border-red-400">...</div>`;
                }
            } catch (error) {
                alert("서버 통신 중 오류가 발생했습니다.");
                console.error("보고서 생성 API 호출 중 네트워크 오류:", error);
            }
        }

        /**
         * '보고서 없이 종료' 버튼의 로직을 처리하는 함수
         */
        async function handleEndDebateWithoutReport() {
            if (!confirm("정말로 토론을 종료하시겠습니까? 토론 내용은 저장되지만, 보고서는 생성되지 않습니다.")) {
                return;
            }

            console.log("토론을 보고서 없이 종료합니다.");
            isPollingActive = false; // 진행 중인 폴링 중단

            const actionPanel = document.getElementById('user-action-panel');
            actionPanel.innerHTML = `<p class="text-center text-slate-600">토론이 종료되었습니다. 주제 입력 화면으로 돌아갑니다...</p>`;

            if (!currentDiscussionId) {
                setTimeout(() => showScreen('screen-topic'), 2000);
                return;
            }

            const token = localStorage.getItem('accessToken');
            try {
                // 새로 추가된 /archive 엔드포인트 호출
                const response = await fetch(`/api/v1/discussions/${currentDiscussionId}/archive`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.ok) {
                    console.log("서버에 토론이 'completed'로 기록되었습니다.");
                } else {
                    const errorData = await response.json();
                    alert("토론 상태를 서버에 저장하는 데 실패했습니다: " + errorData.detail);
                }
            } catch (error) {
                alert("서버 통신 중 오류가 발생했습니다.");
                console.error("토론 아카이브 API 호출 중 네트워크 오류:", error);
            } finally {
                // API 성공/실패와 관계없이 2초 후 주제 입력 화면으로 이동
                setTimeout(() => {
                    currentDiscussionId = null;
                    evidenceDataCache = null;
                    showScreen('screen-topic');
                }, 2000);
            }
        }

        /**
         * 실시간 토론 화면의 모든 UI 요소를 초기 상태로 리셋하는 함수
         */
        function resetDiscussionUI() {
            console.log("Resetting live discussion screen UI for new debate...");

            // 1. 전역 상태 변수 초기화
            displayedMessagesCount = 0;
            regularMessageCount = 0;
            evidenceDataCache = null;
            isPollingActive = false;
            // [스마트 스크롤] 토론 시작 시 자동 스크롤 활성화 (요구사항 1)
            isAutoScrollActive = true;
            userScrolledUp = false;

            // 2. 채팅창 내용 초기화
            const chatbox = document.getElementById('chatbox');
            if (chatbox) {
                chatbox.innerHTML = '<div id="waiting-message" class="text-center text-slate-500">AI 에이전트들의 발언을 기다리고 있습니다...</div>';
            }

            // 3. [스마트 스크롤] 이벤트 리스너 초기화
            initializeSmartScroll();

            // 3. 우측 분석 패널 3종 초기화
            const criticalPanel = document.getElementById('critical-hit-panel');
            if (criticalPanel) {
                criticalPanel.innerHTML = `
                    <h3 class="font-bold text-slate-700 text-lg mb-2">⚡ 결정적 발언</h3>
                    <p class="text-sm text-slate-700">진행 중...</p>
                `;
            }

            const flowPanel = document.getElementById('flow-diagram-container');
            if (flowPanel) {
                flowPanel.innerHTML = '<p class="text-sm text-slate-700">진행 중...</p>';
                flowPanel.style.height = 'auto'; // 높이 자동 조절로 복원
            }

            const stancePanel = document.getElementById('stance-tracker');
            if (stancePanel) {
                stancePanel.innerHTML = '<p class="text-sm text-slate-700">진행 중...</p>';
            }

            // 4. 하단 사용자 액션 패널(버튼 영역) 초기화
            const actionPanel = document.getElementById('user-action-panel');
            if (actionPanel) {
                actionPanel.innerHTML = '';
            }
        }

        /**
         * 대화록 데이터를 받아와 채팅창에 렌더링하는 함수
         */
        function renderTranscript(transcript, participants) {
            const chatbox = document.getElementById('chatbox');
            if (!chatbox) return;

            // 참가자 목록에서 이름과 아이콘을 매핑
            const participantMap = {};
            if (participants) {
                participants.forEach(p => {
                    participantMap[p.name] = { icon: p.icon || '🤖' };
                });
            }

            let html = '';
            if (transcript.length === 0) {
                html = '<div class="text-center text-slate-500">AI 에이전트들의 발언을 기다리고 있습니다...</div>';
            } else {
                transcript.forEach(turn => {
                    const agentName = turn.agent_name;
                    const message = turn.message.replace(/\n/g, '<br>'); // 줄바꿈 처리
                    const icon = participantMap[agentName]?.icon || '🤖';

                    html += `
                        <div class="flex gap-3 my-4 animate-fade-in">
                            <div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">${icon}</div>
                            <div>
                                <p class="text-sm font-bold text-slate-800">${agentName}</p>
                                <div class="bg-slate-100 p-3 rounded-lg mt-1 text-base inline-block">${message}</div>
                            </div>
                        </div>
                    `;
                });
            }
            chatbox.innerHTML = html;
            //chatbox.scrollTop = chatbox.scrollHeight; // 자동 스크롤
        }

        /**
         * Staff 및 시스템 메시지를 위한 통합 렌더링 함수
         */
        function appendSystemMessage(turn) {
            const chatbox = document.getElementById('chatbox');
            const shouldScroll = isScrolledToBottom(chatbox); // 추가 전 위치 확인

            let contentHtml = '';
            
            if (turn.agent_name === 'SNR 전문가' || turn.agent_name === '정보 검증부') {
                const data = JSON.parse(turn.message);
                let icon = '';
                let colorClass = '';

                if (turn.agent_name === 'SNR 전문가') {
                    icon = '📈';
                    colorClass = 'text-blue-600';
                    contentHtml = `<strong>SNR Score:</strong> ${data.snr_score} - ${data.reason}`;
                } else { // 정보 검증부
                    icon = '✅';
                    colorClass = 'text-green-600';
                    if (data.status === '주의 필요') {
                        icon = '⚠️';
                        colorClass = 'text-orange-600';
                    }
                    contentHtml = `<strong>검증 상태:</strong> ${data.reason}`;
                }
                contentHtml = `<div class="flex justify-center items-center gap-2 my-2 text-xs font-semibold animate-fade-in ${colorClass}">
                                 <span>${icon}</span>
                                 <span>[${turn.agent_name}]</span>
                                 <span>${contentHtml}</span>
                               </div>`;

            } else if (turn.agent_name === '사회자' || turn.agent_name === '재판관') {
                contentHtml = `<div class="flex justify-center items-center gap-2 my-4 text-sm text-amber-800 animate-fade-in">
                                 <span class="text-xl">🧑</span>
                                 <span class="font-semibold">${turn.message}</span>
                               </div>`;
            } else if (turn.agent_name === '구분선') {
                contentHtml = `<div class="text-center my-6 font-bold text-gray-400 animate-fade-in">${turn.message}</div>`;
            }

            chatbox.insertAdjacentHTML('beforeend', contentHtml);
            scrollToBottomIfEnabled();
        }

        /**
         * 수신된 대화록을 기반으로 새 메시지만 순차적으로 화면에 추가하는 함수
         */
        async function renderTranscriptWithAnimation(data) {
            const transcript = data.transcript;
            if (!transcript || transcript.length <= displayedMessagesCount) {
                isRendering = false;
                processMessageQueue(); // Check for more messages
                return;
            }

            showGeneralTypingIndicator(false);
            
            const newMessages = transcript.slice(displayedMessagesCount);
            const participantMap = getParticipantMap(data.participants);

            for (const turn of newMessages) {
                const systemAgents = ['SNR 전문가', '정보 검증부', '사회자', '구분선'];

                if (systemAgents.includes(turn.agent_name)) {
                    appendSystemMessage(turn);
                } else {
                    // 브라우저가 백그라운드 상태이면 타이핑 인디케이터와 대기 시간을 건너뜀
                    if (!document.hidden) {
                        const indicator = showTypingIndicator(turn, participantMap);
                        await new Promise(resolve => setTimeout(resolve, 1500 + Math.random() * 1000));
                        indicator.remove();
                    } else {
                        console.log('[renderNewMessages] Browser is hidden. Skipping typing indicator delay.');
                    }

                    const messageContainer = appendMessage(turn, participantMap);
                    const contentSpan = messageContainer.querySelector('.message-content');
                    await typeMessage(contentSpan, turn.message);
                    scrollToBottomIfEnabled();
                }
                displayedMessagesCount++;
                if (!systemAgents.includes(turn.agent_name)) {
                    regularMessageCount++;
                }
            }
            
            renderUxPanels(data);
            checkDiscussionStatus(data); // Check for end of discussion
            
            isRendering = false;
            processMessageQueue(); // After finishing, check if more messages queued up
        }

        /**
         * Staff 에이전트 메시지를 위한 렌더링 함수
         */
        function appendStaffMessage(turn) {
            const chatbox = document.getElementById('chatbox');
            const data = JSON.parse(turn.message);
            let contentHtml = '';
            let icon = '';
            let colorClass = '';

            if (turn.agent_name === 'SNR 전문가') {
                icon = '📈';
                colorClass = 'text-blue-600';
                contentHtml = `<strong>SNR Score:</strong> ${data.snr_score} - ${data.reason}`;
            } else { // 정보 검증부
                icon = '✅';
                colorClass = 'text-green-600';
                if (data.status === '주의 필요') {
                    icon = '⚠️';
                    colorClass = 'text-orange-600';
                }
                contentHtml = `<strong>검증 상태:</strong> ${data.reason}`;
            }

            const staffMessageHtml = `
                <div class="flex justify-center items-center gap-2 my-2 text-xs font-semibold animate-fade-in ${colorClass}">
                    <span>${icon}</span>
                    <span>[${turn.agent_name}]</span>
                    <span>${contentHtml}</span>
                </div>
            `;
            chatbox.insertAdjacentHTML('beforeend', staffMessageHtml);
            chatbox.scrollTop = chatbox.scrollHeight;
        }

        /**
         * '입력 중...' 인디케이터를 생성하고 화면에 추가하는 함수
         */
        function showTypingIndicator(turn, participantMap) {
            const chatbox = document.getElementById('chatbox');
            const agentName = turn.agent_name;
            
            const agentDetails = participantMap[agentName] || {};
            const icon = agentDetails.icon || '🤖';
            const modelName = getModelNameById(agentDetails.model || '');

            const alignment = getAlignmentInfo(regularMessageCount);
            const indicator = document.createElement('div');
            indicator.className = alignment.containerClasses;

            const iconHtml = `<div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">${icon}</div>`;
            
            const typingHtml = `
                <div class="flex flex-col ${alignment.isIconFirst ? '' : 'items-end'}">
                    <p class="text-sm font-bold text-slate-800">${agentName}</p>
                    <p class="text-xs text-slate-500 -mt-1">${modelName}</p>
                    <div class="p-3 rounded-lg mt-1 inline-flex items-center gap-1 ${alignment.bubbleClasses}">
                        <span class="typing-dot animate-bounce">.</span>
                        <span class="typing-dot animate-bounce" style="animation-delay: 0.2s">.</span>
                        <span class="typing-dot animate-bounce" style="animation-delay: 0.4s">.</span>
                    </div>
                </div>`;
            
            indicator.innerHTML = alignment.isIconFirst ? iconHtml + typingHtml : typingHtml + iconHtml;
            
            chatbox.appendChild(indicator);
            scrollToBottomIfEnabled();
            return indicator;
        }

        /**
         * 단일 메시지의 HTML 구조를 만들고, 타이핑 효과를 위해 content span을 비워둠
         */
        function appendMessage(turn, participantMap) {
            const chatbox = document.getElementById('chatbox');
            const agentName = turn.agent_name;
            
            const agentDetails = participantMap[agentName] || {};
            const icon = agentDetails.icon || '🤖';
            const modelName = getModelNameById(agentDetails.model || '');

            const alignment = getAlignmentInfo(regularMessageCount);
            const messageContainer = document.createElement('div');
            messageContainer.className = alignment.containerClasses;

            const iconHtml = `<div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">${icon}</div>`;
            
            const messageHtml = `
                <div class="flex flex-col ${alignment.isIconFirst ? '' : 'items-end'}">
                    <p class="text-sm font-bold text-slate-800">${agentName}</p>
                    <p class="text-xs text-slate-500 -mt-1">${modelName}</p>
                    <div class="p-3 rounded-lg mt-1 text-base inline-block max-w-xl ${alignment.bubbleClasses} ${alignment.textAlignClass}">
                         <span class="message-content"></span>
                    </div>
                </div>`;
            
            messageContainer.innerHTML = alignment.isIconFirst ? iconHtml + messageHtml : messageHtml + iconHtml;

            chatbox.appendChild(messageContainer);
            return messageContainer;
        }

        /**
         * 간단한 마크다운을 HTML로 변환하는 함수
         */
        function markdownToHtml(text) {
            return text
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Bold
                .replace(/\*(.*?)\*/g, '<em>$1</em>')       // Italic
                .replace(/^\s*\*\s(.*)/gm, '<ul><li>$1</li></ul>') // Basic lists
                .replace(/\n/g, '<br>'); // Line breaks
        }

        /**
         * 참가자 정보를 맵으로 만들어주는 헬퍼 함수
         */
        function getParticipantMap(participants) {
            const map = {};
            if (participants) {
                participants.forEach(p => {
                    // 참가자 객체 전체를 저장합니다.
                    map[p.name] = p;
                });
            }
            return map;
        }

        /**
         * 텍스트에 타이핑 효과를 적용하는 함수
         * 브라우저가 백그라운드 상태이면 타이핑 효과를 건너뛰고 즉시 렌더링합니다.
         */
        function typeMessage(element, text) {
            return new Promise(resolve => {
                const htmlText = markdownToHtml(text);

                // 브라우저가 백그라운드(숨겨진 상태)이면 즉시 렌더링
                if (document.hidden) {
                    console.log('[typeMessage] Browser is hidden. Instant rendering.');
                    element.innerHTML = htmlText;
                    resolve();
                    return;
                }

                // 포그라운드 상태일 때는 타이핑 효과 적용
                let i = 0;

                function typing() {
                    if (i < htmlText.length) {
                        if (htmlText.charAt(i) === '<') {
                            const closingTagIndex = htmlText.indexOf('>', i);
                            if (closingTagIndex !== -1) {
                                element.innerHTML += htmlText.substring(i, closingTagIndex + 1);
                                i = closingTagIndex;
                            }
                        } else {
                            element.innerHTML += htmlText.charAt(i);
                        }
                        i++;
                        setTimeout(typing, 20);
                    } else {
                        resolve();
                    }
                }
                typing();
            });
        }

        /**
         * 채팅창 하단에 범용 "입력 중..." 인디케이터를 표시하거나 숨기는 함수
         */
        function showGeneralTypingIndicator(show) {
            const chatbox = document.getElementById('chatbox');
            let indicator = document.getElementById('general-typing-indicator');

            if (show) {
                if (!indicator) {
                    indicator = document.createElement('div');
                    indicator.id = 'general-typing-indicator';
                    indicator.className = 'flex gap-3 my-4';
                    indicator.innerHTML = `
                        <div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">🤖</div>
                        <div>
                            <p class="text-sm font-bold text-slate-800">AI Panel</p>
                            <div class="bg-slate-100 p-3 rounded-lg mt-1 inline-flex items-center gap-1">
                                <span class="typing-dot animate-bounce">.</span>
                                <span class="typing-dot animate-bounce" style="animation-delay: 0.2s">.</span>
                                <span class="typing-dot animate-bounce" style="animation-delay: 0.4s">.</span>
                            </div>
                        </div>`;
                    chatbox.appendChild(indicator);
                    //chatbox.scrollTop = chatbox.scrollHeight;
                }
            } else {
                if (indicator) {
                    indicator.remove();
                }
            }
        }

        /**
         * 특정 에이전트의 "입력 중..." 인디케이터를 생성하고 반환하는 함수 (수정된 버전)
         */
        function showTypingIndicator(turn, participantMap, shouldScroll) {
            const chatbox = document.getElementById('chatbox');
            const agentName = turn.agent_name;
            
            // participantMap에서 에이전트의 전체 정보를 가져옵니다.
            const agentDetails = participantMap[agentName] || {};
            const icon = agentDetails.icon || '🤖';
            const modelName = agentDetails.model || ''; // 모델 이름 추출

            const alignment = getAlignmentInfo(regularMessageCount);
            const indicator = document.createElement('div');
            indicator.className = alignment.containerClasses;

            const iconHtml = `<div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">${icon}</div>`;
            
            // [수정] 에이전트 이름 아래에 모델명을 표시하는 HTML 추가
            const typingHtml = `
                <div class="flex flex-col ${alignment.isIconFirst ? '' : 'items-end'}">
                    <p class="text-sm font-bold text-slate-800">${agentName}</p>
                    <p class="text-xs text-slate-500 -mt-1">${modelName}</p>
                    <div class="p-3 rounded-lg mt-1 inline-flex items-center gap-1 ${alignment.bubbleClasses}">
                        <span class="typing-dot animate-bounce">.</span>
                        <span class="typing-dot animate-bounce" style="animation-delay: 0.2s">.</span>
                        <span class="typing-dot animate-bounce" style="animation-delay: 0.4s">.</span>
                    </div>
                </div>`;
            
            indicator.innerHTML = alignment.isIconFirst ? iconHtml + typingHtml : typingHtml + iconHtml;
            
            chatbox.appendChild(indicator);
            if (shouldScroll) {
                chatbox.scrollTop = chatbox.scrollHeight;
            }
            return indicator;
        }

        /**
         * '토론 흐름도' 패널을 원형으로 렌더링하는 새로운 함수
         */
        function renderCircularFlowDiagram(interactions, participants) {
            const container = document.getElementById('flow-diagram-container');
            
            // --- [로그 #1: 데이터 수신 확인] ---
            // 이 로그는 백엔드에서 상호작용 데이터가 정상적으로 넘어왔는지 확인하는 첫 관문입니다.
            console.log('%c[Flow Diagram] 1. Rendering Started', 'color: blue; font-weight: bold;', {
                'Received Interactions': interactions,
                'Received Participants': participants
            });

            if (!container) {
                console.error('[Flow Diagram] Error: Container element #flow-diagram-container not found!');
                return;
            }
            // [로그 추가] interactions 데이터가 없거나 비어있는 경우, 명시적으로 로그를 남기고 함수를 종료합니다.
            if (!interactions || interactions.length === 0) {
                console.warn('[Flow Diagram] ⚠️ Warning: No interactions data to display. Arrow rendering will be skipped.');
                container.innerHTML = '<p class="text-sm text-center text-slate-500">이번 라운드에서는 에이전트 간의 직접적인 상호작용이 감지되지 않았습니다.</p>';
                container.style.height = 'auto'; // 높이 초기화
                return;
            }

            container.innerHTML = ''; // 컨테이너 초기화
            container.style.height = '250px';

            const participantMap = getParticipantMap(participants);
            const juryNames = participants
                .filter(p => p.name !== '재판관')
                .map(p => p.name);

            const agentNodes = {};
            const radius = 100;
            const centerX = container.offsetWidth / 2;
            const centerY = container.offsetHeight / 2;

            // 에이전트 아이콘을 원형으로 배치 (이 부분은 정상 동작하므로 로그 생략)
            juryNames.forEach((name, i) => {
                const angle = (i / juryNames.length) * 2 * Math.PI - (Math.PI / 2);
                const x = centerX + radius * Math.cos(angle) - 24;
                const y = centerY + radius * Math.sin(angle) - 24;

                const agentNode = document.createElement('div');
                agentNode.id = `agent-node-${name.replace(/[^a-zA-Z0-9]/g, '-')}`;
                agentNode.className = 'flex flex-col items-center text-center cursor-pointer absolute';
                agentNode.style.left = `${x}px`;
                agentNode.style.top = `${y}px`;
                agentNode.innerHTML = `
                    <div class="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-2xl">${participantMap[name].icon}</div>
                    <p class="text-xs font-bold mt-1 w-20 truncate">${name}</p>
                `;
                container.appendChild(agentNode);
                agentNodes[name] = agentNode;
            });

            // DOM 렌더링 후 화살표 그리기
            setTimeout(() => {
                const lines = [];
                
                // --- [로그 #2: 상호작용 루프 실행 확인] ---
                // 이 로그는 수신된 interactions 배열을 순회하며 화살표를 그리려는 시도가 시작되었음을 보여줍니다.
                console.log('%c[Flow Diagram] 2. Starting to draw arrows...', 'color: blue;');

                interactions.forEach((flow, index) => {
                    const fromNode = agentNodes[flow.from];
                    const toNode = agentNodes[flow.to];
                    
                    // --- [로그 #3: 노드 존재 여부 확인] ---
                    // 이 로그는 화살표를 그릴 시작점(from)과 끝점(to)이 DOM에 실제로 존재하는지 확인합니다.
                    if (fromNode && toNode) {
                        console.log(`[Flow Diagram] 2.1. Drawing arrow #${index + 1}: ${flow.from} -> ${flow.to}`);
                        const colorClass = `flow-line-color-${juryNames.indexOf(flow.from) % 7}`;
                        const line = createFlowLine(fromNode, toNode, colorClass);
                        line.dataset.fromAgent = flow.from;
                        container.appendChild(line);
                        lines.push(line);
                    } else {
                        // 만약 노드를 찾지 못했다면, 왜 실패했는지 상세한 정보를 로그로 남깁니다.
                        console.error(`[Flow Diagram] ❌ Error: Could not find nodes for flow: ${flow.from} -> ${flow.to}`,
                            {
                                'From Node Found': !!fromNode,
                                'To Node Found': !!toNode,
                                'Agent Nodes Map': agentNodes
                            });
                    }
                });

                // --- [로그 #4: 마우스 이벤트 리스너 추가 확인] ---
                console.log('%c[Flow Diagram] 3. Adding mouse event listeners to agent nodes.', 'color: blue;');

                // 모든 에이전트 노드에 마우스 이벤트 리스너 추가
                Object.values(agentNodes).forEach(node => {
                    node.addEventListener('mouseenter', () => {
                        const agentName = node.querySelector('p').textContent;
                        lines.forEach(line => {
                            if (line.dataset.fromAgent === agentName) {
                                line.classList.add('highlighted');
                                line.classList.remove('dimmed');
                            } else {
                                line.classList.add('dimmed');
                                line.classList.remove('highlighted');
                            }
                        });
                    });

                    node.addEventListener('mouseleave', () => {
                        lines.forEach(line => {
                            line.classList.remove('highlighted', 'dimmed');
                        });
                    });
                });

            }, 100); // DOM이 렌더링될 시간을 줍니다.
        }

        // --- Event Listeners ---
        loginButton.addEventListener('click', handleLogin);
        logoutButton.addEventListener('click', handleLogout);
        startAnalysisButton.addEventListener('click', handleOrchestration);

        // 파일 입력 변경 시 파일 이름 표시
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                fileNameDisplay.textContent = fileInput.files[0].name;
            } else {
                fileNameDisplay.textContent = '참고 파일 첨부 (TXT, PDF)';
            }
        });

        // 로그인 폼에서 Enter 키 입력 시 로그인 시도
        document.getElementById('login-form').addEventListener('keyup', (event) => {
            if (event.key === 'Enter') {
                handleLogin();
            }
        });

        // --- Initial Setup ---
        function updateUIForLoggedInState() {
            const userEmail = localStorage.getItem('userEmail');
            if (userEmail) {
                userEmailDisplay.textContent = userEmail;
            }
        }

        function updateUIForLoggedOutState() {
            userEmailDisplay.textContent = '';
            emailInput.value = '';
            passwordInput.value = '';
        }

        // 페이지 로드 시 실행
        document.addEventListener('DOMContentLoaded', () => {
            const token = localStorage.getItem('accessToken');
            const rememberedEmail = localStorage.getItem('rememberedEmail');
            const rememberedPassword = localStorage.getItem('rememberedPassword');

            if (rememberedEmail) {
                emailInput.value = rememberedEmail;
                document.getElementById('remember-me-checkbox').checked = true;
            }
            if (rememberedPassword) {
                passwordInput.value = rememberedPassword;
            }

            if (token) {
                console.log('기존 토큰이 유효합니다. 주제 입력 화면으로 이동합니다.');
                updateUIForLoggedInState();
                showScreen('screen-topic');
            } else {
                console.log('로그인 토큰이 없습니다. 로그인 화면을 표시합니다.');
                showScreen('screen-login');
            }

            // [스마트 스크롤] 기존 중복 코드 제거됨 - initializeSmartScroll()로 통합됨

            // HTML 복사 버튼 이벤트 리스너
            document.getElementById('copy-report-html-btn').addEventListener('click', () => {
                const iframe = document.getElementById('report-modal-iframe');
                const reportHtml = iframe.srcdoc;
                navigator.clipboard.writeText(reportHtml).then(() => {
                    alert('보고서 HTML이 클립보드에 복사되었습니다.');
                }).catch(err => {
                    console.error('HTML 복사 실패: ', err);
                    alert('HTML 복사에 실패했습니다.');
                });
            });
                    });
