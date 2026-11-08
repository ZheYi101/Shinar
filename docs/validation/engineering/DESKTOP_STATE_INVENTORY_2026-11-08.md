# 桌面门面字段迁移清单

基于 `d72819c` 的 AST 赋值扫描；列出原写入方法及迁移后的唯一所有者。容器内元素修改由对应所有者命令接管，不保留门面可写别名。主验收见 [治理记录](DESKTOP_STATE_OWNERSHIP_2026-11-08.md)。

## src/shinar/desktop/presentation/conversation_presentation.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_confirmed` | `__init__`, `apply` | ConversationPresentation（保留） |
| `_generation` | `__init__`, `apply` | ConversationPresentation（保留） |
| `_settled` | `__init__`, `apply` | ConversationPresentation（保留） |
| `_snapshot` | `__init__`, `apply` | ConversationPresentation（保留） |
| `_text_done` | `__init__`, `apply` | ConversationPresentation（保留） |

## src/shinar/desktop/presentation/conversation_view.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_feedback_items` | `_conversation_feedback` | ReviewProjection |
| `_presentation_generation` | `new_presentation_token` | SessionEditing |
| `draft` | `present_conversation` | SessionEditing |

## src/shinar/desktop/presentation/properties.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_custom_topic` | `customTopic` | MaterialProjection |
| `_draft` | `draft` | SessionEditing |
| `_draft_revision` | `draft` | SessionEditing |
| `_practice_mode` | `practiceMode` | MaterialProjection |
| `_role_description` | `roleDescription` | MaterialProjection |
| `_topic_filter` | `topicFilter` | MaterialProjection |
| `_topic_search` | `topicSearch` | MaterialProjection |

## src/shinar/desktop/presentation/viewmodel.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_analysis_identity` | `__init__`, `_poll_preparation` | MaterialProjection |
| `_audio` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_busy` | `__init__`, `run_operation`, `_operation_completed` | LearningOperations |
| `_closed` | `__init__`, `begin_shutdown` | LearningOperations |
| `_conversation` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_custom_topic` | `__init__`, `selectMaterial`, `resetSession`, `selectTopic`, `after_started` | MaterialProjection |
| `_draft` | `__init__`, `selectSession`, `selectMaterial`, `resetSession`, `after_started` | SessionEditing |
| `_draft_revision` | `__init__` | SessionEditing |
| `_feedback_items` | `__init__`, `resetSession` | ReviewProjection |
| `_last_reply` | `__init__`, `restore_last_reply`, `after_started`, `_clear_audio` | SessionEditing |
| `_local_speech` | `__init__`, `configure_local_speech` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_on_success` | `__init__`, `run_operation`, `_operation_completed` | LearningOperations |
| `_practice_mode` | `__init__` | MaterialProjection |
| `_preferences` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_preparation_state` | `__init__`, `_poll_preparation` | MaterialProjection |
| `_preparation_timer` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_presentation_generation` | `__init__` | SessionEditing |
| `_provider_label` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_retry_operation` | `__init__`, `run_operation`, `_operation_completed`, `_clear_audio` | LearningOperations |
| `_review_items` | `__init__`, `resetSession`, `_refresh_review_items` | ReviewProjection |
| `_role_description` | `__init__` | MaterialProjection |
| `_selected_topic` | `__init__`, `selectSession`, `selectMaterial`, `resetSession`, `_after_material_loaded`, `selectTopic`, `after_started` | MaterialProjection |
| `_session_drafts` | `__init__` | SessionEditing |
| `_speech_status` | `__init__`, `_local_speech_status` | LearningOperations |
| `_status` | `__init__`, `_set_status` | LearningOperations |
| `_stt` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_topic_filter` | `__init__`, `selectMaterial`, `_after_material_loaded` | MaterialProjection |
| `_topic_search` | `__init__`, `selectMaterial`, `_after_material_loaded` | MaterialProjection |
| `_tts` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_workbench` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_worker` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `draft` | `useDirection` | SessionEditing |
| `source_context_provider` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `voice` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |

## src/shinar/desktop/workspace/controller.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_browsing` | `__init__`, `browseMaterial`, `openThread`, `_started`, `commitImport` | WorkspaceNavigation |
| `_category` | `__init__`, `setCategory` | WorkspaceNavigation |
| `_closed` | `__init__`, `begin_shutdown` | WorkspaceNavigation |
| `_collapsed` | `__init__`, `toggleSidebar` | WorkspaceNavigation |
| `_cursor` | `__init__`, `saveEditor`, `openThread`, `_started` | WorkspaceNavigation |
| `_document_ready` | `__init__` | ReadingCoordinator |
| `_error` | `__init__`, `navigate`, `_fail`, `inspectFile`, `locateSentence` | WorkspaceNavigation |
| `_expanded` | `__init__` | WorkspaceNavigation |
| `_import_language` | `__init__`, `importLanguage` | ImportEditor |
| `_import_mode` | `__init__`, `setImportMode` | ImportEditor |
| `_import_text` | `__init__`, `importText`, `saveScope`, `saved` | ImportEditor |
| `_import_title` | `__init__`, `importTitle`, `inspectFile`, `saveScope`, `received`, `saved` | ImportEditor |
| `_imported` | `__init__`, `inspectFile`, `saveScope`, `received`, `saved` | ImportEditor |
| `_inspecting` | `__init__`, `_completed`, `inspectFile` | ImportEditor |
| `_jobs` | `__init__` | WorkspaceJobs（沿用 AsyncWorker） |
| `_materials` | `__init__`, `refresh` | WorkspaceNavigation |
| `_opening` | `__init__` | WorkspaceNavigation |
| `_pending_position` | `__init__`, `navigate` | ReadingCoordinator |
| `_pending_search` | `__init__`, `begin_shutdown` | ReadingCoordinator |
| `_preview` | `__init__`, `navigate`, `openThread`, `_started` | ReadingCoordinator |
| `_reader_book` | `__init__` | ReadingCoordinator |
| `_reader_error` | `__init__` | ReadingCoordinator |
| `_reader_generation` | `__init__` | ReadingCoordinator |
| `_reader_id` | `__init__` | ReadingCoordinator |
| `_reader_position` | `__init__`, `openThread`, `_started` | ReadingCoordinator |
| `_reader_target` | `__init__` | ReadingCoordinator |
| `_request` | `__init__` | ImportEditor.tasks／ReadingCoordinator.document_tasks、search_tasks |
| `_results` | `__init__` | ReadingCoordinator |
| `_route` | `__init__`, `navigate` | WorkspaceNavigation |
| `_scope_import_material` | `__init__`, `commitImport`, `saveScope`, `saved` | ReadingCoordinator |
| `_scope_pending` | `__init__` | ReadingCoordinator |
| `_scope_return_route` | `__init__`, `openScope` | ReadingCoordinator |
| `_scroll` | `__init__`, `saveEditor`, `openThread`, `_started` | WorkspaceNavigation |
| `_search_timer` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_sections` | `__init__` | ReadingCoordinator |
| `_source_end` | `__init__` | ReadingCoordinator |
| `_source_full` | `__init__` | ReadingCoordinator |
| `_source_limit` | `__init__` | ReadingCoordinator |
| `_source_material` | `__init__` | ReadingCoordinator |
| `_source_offset` | `__init__` | ReadingCoordinator |
| `_source_open` | `__init__`, `openThread`, `_started` | ReadingCoordinator |
| `_source_scroll` | `__init__`, `openThread`, `_started` | ReadingCoordinator |
| `_source_section` | `__init__`, `openThread`, `_started` | ReadingCoordinator |
| `_source_snapshot` | `__init__`, `openThread`, `_started` | ReadingCoordinator |
| `_source_stale` | `__init__` | ReadingCoordinator |
| `_source_text` | `__init__` | ReadingCoordinator |
| `_states` | `__init__` | WorkspaceNavigation.positions／ReadingCoordinator.records（按职责拆分） |
| `_threads` | `__init__`, `refresh` | WorkspaceNavigation |
| `_worker` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `settings` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `vm` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `workbench` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |

## src/shinar/desktop/workspace/reader_runtime.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_bridge` | `__init__` | ReaderRuntime／ReaderBridge（Qt 适配，保留） |
| `_profile` | `__init__` | ReaderRuntime／ReaderBridge（Qt 适配，保留） |
| `_url` | `__init__` | ReaderRuntime／ReaderBridge（Qt 适配，保留） |
| `requests` | `__init__` | ReaderRuntime／ReaderBridge（Qt 适配，保留） |

## src/shinar/desktop/workspace/reading.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_document_ready` | `loadSource`, `previewMessage`, `received` | ReadingCoordinator |
| `_pending_position` | `loadSource`, `_show_position`, `previewMessage`, `received` | ReadingCoordinator |
| `_pending_search` | `scheduleSourceSearch`, `_search_after_pause` | ReadingCoordinator |
| `_preview` | `toggleSource`, `_select_source_range`, `previewMessage`, `closePreview` | ReadingCoordinator |
| `_reader_book` | `loadSource`, `previewMessage`, `received` | ReadingCoordinator |
| `_reader_error` | `readerFailed`, `loadSource`, `received` | ReadingCoordinator |
| `_reader_generation` | `loadSource`, `received` | ReadingCoordinator |
| `_reader_id` | `loadSource`, `previewMessage`, `received` | ReadingCoordinator |
| `_reader_position` | `saveReaderPosition`, `selectSection` | ReadingCoordinator |
| `_reader_target` | `loadSource`, `_show_position` | ReadingCoordinator |
| `_results` | `loadSource`, `_set_results`, `previewMessage` | ReadingCoordinator |
| `_sections` | `loadSource`, `previewMessage`, `received` | ReadingCoordinator |
| `_source_end` | `loadSource`, `previewMessage` | ReadingCoordinator |
| `_source_full` | `loadSource`, `previewMessage`, `received` | ReadingCoordinator |
| `_source_limit` | `loadSource`, `_show_position`, `previewMessage`, `received` | ReadingCoordinator |
| `_source_material` | `loadSource` | ReadingCoordinator |
| `_source_offset` | `loadSource`, `_show_position`, `previewMessage`, `received` | ReadingCoordinator |
| `_source_open` | `toggleSource`, `previewMessage` | ReadingCoordinator |
| `_source_scroll` | `saveSourceScroll`, `selectSection` | ReadingCoordinator |
| `_source_section` | `loadSource`, `_select_source_range`, `received` | ReadingCoordinator |
| `_source_snapshot` | `selectSection`, `_select_source_range`, `clearSource` | ReadingCoordinator |
| `_source_stale` | `loadSource`, `previewMessage`, `received` | ReadingCoordinator |
| `_source_text` | `loadSource`, `loadMoreSource`, `_show_position`, `previewMessage`, `received` | ReadingCoordinator |

## src/shinar/desktop/speech_library/jobs.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_closing` | `__init__`, `begin_shutdown` | SpeechPreparationJobs（保留） |
| `_jobs` | `__init__` | SpeechPreparationJobs（保留） |
| `_lock` | `__init__` | SpeechPreparationJobs（保留） |
| `_rows` | `__init__` | SpeechPreparationJobs（保留） |
| `_timer` | `__init__` | SpeechPreparationJobs（保留） |
| `concurrency` | `__init__` | SpeechPreparationJobs（保留） |

## src/shinar/desktop/speech_library/operations.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_status` | `setCompute`, `prepareRuntime`, `releaseModels`, `select` | LibraryOperations |

## src/shinar/desktop/speech_library/viewmodel.py

| 原字段 | 原写入方法 | 最终归属 |
| --- | --- | --- |
| `_audio` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_busy` | `__init__`, `_start`, `_finish` | LibraryOperations |
| `_cancel` | `__init__`, `_start` | LibraryOperations |
| `_closing` | `__init__`, `begin_shutdown` | LibraryOperations |
| `_download_revision` | `__init__`, `_download_activity` | CatalogProjection |
| `_downloads` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_hardware` | `__init__`, `_finish` | CatalogProjection |
| `_language` | `__init__`, `setFilter` | CatalogProjection |
| `_last_setup_error` | `__init__`, `_start`, `run` | LibraryOperations |
| `_operation` | `__init__`, `_start` | LibraryOperations |
| `_player` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_preview_device` | `__init__`, `configure_preview` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_progress` | `__init__`, `_download_progress`, `_start` | LibraryOperations |
| `_progress_lock` | `__init__` | LibraryOperations |
| `_refresh_pending` | `__init__`, `_download_finished`, `_finish` | CatalogProjection |
| `_resource_thread` | `__init__`, `_poll_resources` | ResourceMonitor |
| `_resource_timer` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_resources` | `__init__`, `_set_resources` | ResourceMonitor |
| `_rows` | `__init__`, `_finish` | CatalogProjection |
| `_runtimes` | `__init__`, `_finish` | CatalogProjection |
| `_scenario` | `__init__`, `setFilter` | CatalogProjection |
| `_status` | `__init__`, `_setup_status`, `_inference_status`, `_start`, `_finish`, `preview`, `_playback_error` | LibraryOperations |
| `_storage_usage` | `__init__`, `_finish` | CatalogProjection |
| `_thread` | `__init__`, `_start` | LibraryOperations |
| `_timer` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `_voice_active` | `__init__`, `configure_preview` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `catalog` | `__init__` | CatalogProjection |
| `local_service` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |
| `store` | `__init__` | 原 Qt 门面（设备／计时器／配置／公开依赖端口，保留） |

## 任务、资源和失效边界

| 工作 | 输入／事件 | 取消与收尾责任 |
| --- | --- | --- |
| 语音目录／环境／测速 | LibraryRequest 冻结路径、模型 JSON、语言／场景和计算配置；LibraryEvent 保留任务身份 | LibraryOperations 的取消句柄与实际线程；Qt 主线程接受结果后更新目录，合并一次待刷新 |
| 并行下载 | SpeechPreparationJobs 的既有队列、原模型／语言及每项取消句柄 | 保留原队列和临时目录／校验／原子发布；等待实际下载线程 |
| 资源监测 | 启动前捕获进程 ID；独立扫描身份 | ResourceMonitor 停用、关闭后拒绝旧结果，等待扫描线程 |
| 学习业务操作 | OperationIdentity 包含实例／任务／代际／原材料与会话；回调保存在 LearningOperations | 主线程按原任务 ID 接收；退出清空回调／重试，AsyncWorker 等待真实执行器及进程 |
| 导入／文档／搜索 | 各自 TaskLane；WorkspaceJobs 复制冻结输入，界面回调不进入后台 | 分职责失效；搜索先失效再 200ms 防抖；退出禁止新任务并等待实际 worker |
| Qt 音频／计时器／WebEngine | 主线程适配；ReadingRuntime 只提供明确操作与查询端口 | 门面停止设备和计时器，ReaderRuntime 保留原 profile／白名单；模型服务仍由 ViewModel 清理 |

统一退出仍为 5 秒协作取消、15 秒总预算；未结束时保留错误及重试，不把取消 future 当作线程或所属进程已经结束。
