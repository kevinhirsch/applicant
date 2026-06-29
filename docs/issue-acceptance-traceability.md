# Issue acceptance traceability — requirement ↔ acceptance ↔ code

Master sheet for implementing the open tracker. Every open issue has an executable
acceptance spec (Gherkin) + a DeepSeek-ready work-order comment on GitHub. Untagged
scenarios = GREEN regression guards for shipped behaviour; `@pending` = TDD reds
(xfail via `tests/bdd/conftest.py`). Definition of done per issue = its `@pending`
scenarios pass + `ruff check .` + full hermetic suite green + single Alembic head.

**212 issues** · 140 green · 395 pending.

| Issue | Requirement / acceptance | Feature | Step module | green | pending |
|---|---|---|---|---|---|
| #141 | # Issue #141 — FR-CUA / FR-RESUME-4 — application/services/prefill_service.py | `enh_141_loop_desktop_assist_upload.feature` | `test_enh_t12_cua_steps.py` | 3 | 2 |
| #142 | # Issue #142 — FR-CUA-2 — adapters/sandbox/computer_use/cua_driver.py | `enh_142_cua_driver_tool_reconcile.feature` | `test_enh_t12_cua_steps.py` | 2 | 2 |
| #143 | # Issue #143 — FR-MIND-8 / FR-MIND-13 — application/services/context_manager.py | `enh_143_context_management.feature` | `test_enh_t12_cua_steps.py` | 6 | 0 |
| #144 | # Issue #144 — FR-MIND-6 / FR-CUA-2 — application/services/loop_tools.py + chat_tools.py | `enh_144_agent_callable_tools.feature` | `test_enh_t12_cua_steps.py` | 4 | 2 |
| #145 | # Issue #145 — FR-MIND §10 — adapters/memory/factory.py + adapters/memory/bridge.py | `enh_145_mind_bridge_e2e.feature` | `test_enh_t12_cua_steps.py` | 2 | 3 |
| #160 | The takeover desktop base image is pinned to an immutable digest | `enh_160_mutable_base_tag.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #161 | Application container images declare a non-root runtime user | `enh_161_root_user_dockerfile.feature` | `test_enh_t01_security_steps.py` | -1 | 3 |
| #162 | Locked dependencies are at or above their advisory-fixed releases | `enh_162_vulnerable_deps.feature` | `test_enh_t01_security_steps.py` | 2 | 0 |
| #163 | File reads are contained to an allowed base directory | `enh_163_path_traversal_reads.feature` | `test_enh_t01_security_steps.py` | 0 | 2 |
| #164 | Build-time remote fetches are integrity verified | `enh_164_unverified_remote_fetch.feature` | `test_enh_t01_security_steps.py` | -1 | 3 |
| #167 | CI checkout steps do not persist Git credentials on the runner | `enh_167_checkout_persists_credentials.feature` | `test_enh_t01_security_steps.py` | 0 | 3 |
| #169 | # Issue #169 — adapters/storage/app_config_store.py + adapters/tools/tool_settings_sink.py | `enh_169_select_then_insert_unique.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #170 | Résumé parser preserves parenthesized contact and history fields | `enh_170_phone_paren.feature` | `test_enh_t07_materials_steps.py` | 1 | 1 |
| #171 | # Issue #171 — Greenhouse/Lever ATS adapters are shells (adapters/browser/ats.py) — FR-PREFILL-2 / NFR-EXT-1 | `enh_171_greenhouse_lever_shells.feature` | `test_enh_t03_ats_steps.py` | 2 | 2 |
| #172 | Quiet hours silence non-critical notifications instead of firing 24/7 | `enh_172_quiet_hours.feature` | `test_enh_t06_notifications_steps.py` | 2 | 2 |
| #173 | # Issue #173 — Unknown ATS falls through to Workday (adapters/browser/ats.py resolve_ats) — FR-PREFILL-2 | `enh_173_unknown_ats_fallback.feature` | `test_enh_t03_ats_steps.py` | 2 | 1 |
| #174 | Real integrations are opt-in and a production preset could flip them together | `enh_174_hermetic_lane_defaults.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #175 | Automated account creation is off by default and could allow per-tenant credentials | `enh_175_automated_accounts_default.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #176 | Multi-campaign switcher front-door wiring | `enh_176_multi_campaign_switcher_dormant.feature` | `test_enh_t08_frontend_steps.py` | 1 | 1 |
| #177 | # Issue #177 — No ATS detection on pre-fill failure (application/services/prefill_service.py) — FR-PREFILL-2/6 | `enh_177_ats_detection_match_rate.feature` | `test_enh_t03_ats_steps.py` | 0 | 2 |
| #178 | Résumé rendering degrades honestly when render binaries are absent | `enh_178_render_stub_path.feature` | `test_enh_t07_materials_steps.py` | 3 | 1 |
| #179 | # Issue #179 — FR-CUA — adapters/sandbox/computer_use/* + dormant.py + docker/webtop-chrome | `enh_179_desktop_assist_image_bake.feature` | `test_enh_t12_cua_steps.py` | 3 | 2 |
| #180 | # Issue #180 — application/services/agent_loop.py (ResumeLedger) + app/container.py | `enh_180_agentloop_per_tick_state.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #181 | The real-adapter integration tests actually run in a CI lane | `enh_181_integration_lane.feature` | `test_enh_t10_deploy_steps.py` | 2 | 1 |
| #182 | Chat-driven steering of the autonomous loop | `enh_182_chat_steering_incomplete.feature` | `test_enh_t08_frontend_steps.py` | 1 | 2 |
| #183 | The frozen port and container contract is enforced, not just commented | `enh_183_frozen_container_enforcement.feature` | `test_enh_t10_deploy_steps.py` | 1 | 1 |
| #184 | # Issue #184 — Compare surface present-but-disabled — workspace/src/applicant_features.py | `enh_184_compare_present_but_disabled.feature` | `test_enh_t11_integration_steps.py` | 1 | 2 |
| #185 | # Issue #185 — app/config.py SCHEDULER_ENABLED + app/lifespan.py | `enh_185_scheduler_enabled_default.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #186 | LLM rate limiting is wired but defaults to disabled | `enh_186_llm_rate_limit_default.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #187 | Résumé aggressiveness dial is wired backend-side and never relaxes truthfulness | `enh_187_aggressiveness_dial.feature` | `test_enh_t07_materials_steps.py` | 3 | 1 |
| #188 | The engine reports which capabilities are real versus stubbed at startup | `enh_188_startup_capability_report.feature` | `test_enh_t10_deploy_steps.py` | 2 | 1 |
| #189 | # Issue #189 — adapters/orchestration/dbos_orchestrator.py (_INDEFINITE_WAIT_SECONDS) | `enh_189_approval_timeout_config.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #190 | # Issue #190 — No post-submission lifecycle (core/state_machine.py, core/entities/outcome_event.py) — FR-LOG-4/FR-LEARN-2 | `enh_190_post_submission_lifecycle.feature` | `test_enh_t03_ats_steps.py` | 2 | 2 |
| #191 | # Issue #191 — No rejection detection (no IMAP/Gmail/ATS status polling) — FR-LEARN-2 | `enh_191_rejection_detection.feature` | `test_enh_t03_ats_steps.py` | 0 | 2 |
| #192 | # Issue #192 — No ghosting/silence tracking (no SLA / time-since-submission) — FR-LOG-4 | `enh_192_ghosting_silence_tracking.feature` | `test_enh_t03_ats_steps.py` | 0 | 2 |
| #193 | # Issue #193 — No automated follow-up emails (thank-you / check-in) — FR-LOG-4 | `enh_193_followup_emails.feature` | `test_enh_t03_ats_steps.py` | 0 | 2 |
| #194 | Internationalized field parsing in the engine | `enh_194_us_english_hardcoded.feature` | `test_enh_t08_frontend_steps.py` | 0 | 3 |
| #195 | Throughput is capped per campaign but not per job board | `enh_195_per_board_rate_limiting.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #196 | Discovery dedups within a run but not across runs | `enh_196_cross_run_dedup.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #197 | Application attachments beyond résumé and cover letter | `enh_197_attachment_types.feature` | `test_enh_t07_materials_steps.py` | 1 | 2 |
| #198 | # Issue #198 — _force_status bypasses the state machine (application/services/agent_loop.py) — §7 state machine | `enh_198_force_status_bypass.feature` | `test_enh_t03_ats_steps.py` | 2 | 1 |
| #199 | Two-layer feature gating for live dormant surfaces | `enh_199_live_dormant_surface_gating.feature` | `test_enh_t08_frontend_steps.py` | 1 | 2 |
| #200 | Delivery-status integration-skip count is accurate | `enh_200_delivery_status_skip_undercount.feature` | `test_enh_t08_frontend_steps.py` | -1 | 2 |
| #201 | README front-door surface claims match the section wiring | `enh_201_readme_surface_count.feature` | `test_enh_t08_frontend_steps.py` | 1 | 1 |
| #202 | # Issue #202 — prefill credential lookup / application/services/prefill_service.py:_lookup_credential | `enh_202_credential_tenant_lookup_failure.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #203 | # Issue #203 — prefill credential lookup / application/services/prefill_service.py:_lookup_credential | `enh_203_credential_scope_retrieve_failure.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #204 | # Issue #204 — prefill account creation / application/services/prefill_service.py:_capture_credential | `enh_204_capture_credential_silent_loss.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #205 | # Issue #205 — prefill field fill / application/services/prefill_service.py:_fill_current_page | `enh_205_fill_field_audit_trail.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #206 | # Issue #206 — sensitive-field detection / core/rules/sensitive_fields.py + prefill _resolve_value | `enh_206_sensitive_attribute_flag.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #207 | # Issue #207 — prefill loop resilience / application/services/prefill_service.py:_continue_pages | `enh_207_browser_health_check.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #208 | # Issue #208 — prefill state access / application/services/prefill_service.py:_check_detection etc. | `enh_208_current_state_none_guard.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #209 | # Issue #209 — _is_screening_question classifies by word count >=6 (application/services/prefill_service.py) — FR-ANSWER-1 | `enh_209_screening_word_count.feature` | `test_enh_t03_ats_steps.py` | 2 | 1 |
| #210 | # Issue #210 — attribute lookup priority / application/services/prefill_service.py:_lookup | `enh_210_attribute_match_priority.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #211 | # Issue #211 — LLM escalation / application/services/prefill_service.py:_escalate_mapping | `enh_211_llm_unavailable_diagnostic.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #212 | # Issue #212 — page settle / adapters/browser/page_source.py:_settle (PlaywrightPageSource) | `enh_212_settle_timeout_empty_dom.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #213 | # Issue #213 — account-gate parity / adapters/browser/page_source.py:FakePageSource.is_account_gate | `enh_213_account_gate_signin_only.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #214 | # Issue #214 — Workday model is exactly 6 fixed pages (adapters/browser/ats.py) — FR-PREFILL-2 | `enh_214_workday_fixed_pages.feature` | `test_enh_t03_ats_steps.py` | 1 | 1 |
| #215 | # Issue #215 — stealth fingerprint coherence / adapters/browser/stealth.py:PINNED_CHROME_MAJOR | `enh_215_chrome_major_override.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #216 | # Issue #216 — profile concurrency / adapters/browser/stealth.py:ProfileStore.for_tenant | `enh_216_profile_visit_count_race.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #217 | # Issue #217 — browser session lifecycle / adapters/browser/patchright_browser.py:_sessions | `enh_217_browser_session_dispose.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #218 | # Issue #218 — adapters/orchestration/checkpoint_shim.py | `enh_218_checkpoint_corruption_detection.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #219 | # Issue #219 — adapters/orchestration/checkpoint_shim.py (_save) | `enh_219_checkpoint_disk_full.feature` | `test_enh_t04_orchestration_steps.py` | 0 | 2 |
| #220 | # Issue #220 — adapters/orchestration/checkpoint_shim.py (_lock_for / run_step) | `enh_220_concurrent_checkpoint_writes.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #221 | # Issue #221 — application/workflows/application_pipeline.py (teardown step) | `enh_221_teardown_idempotency.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #222 | # Issue #222 — LLM escalation defence in depth / application/services/prefill_service.py:_escalate_mapping | `enh_222_escalation_prompt_redacts_sensitive.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #223 | # Issue #223 — login error classification / application/services/prefill_service.py:_try_log_in | `enh_223_login_error_vs_wrong_password.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #224 | # Issue #224 — PageSource contract parity / adapters/browser/page_source.py:PageSource Protocol | `enh_224_page_source_submit_account_protocol.feature` | `test_enh_t02_prefill_steps.py` | 0 | 2 |
| #225 | # Issue #225 — Dropdown/combobox matching has zero fake-model coverage (adapters/browser/page_source.py) — FR-PREFILL-3 | `enh_225_dropdown_fake_coverage.feature` | `test_enh_t03_ats_steps.py` | 2 | 1 |
| #226 | # Issue #226 — _pick_visible_option not scoped to the opened dropdown (adapters/browser/page_source.py) — FR-PREFILL-3 | `enh_226_pick_option_scoping.feature` | `test_enh_t03_ats_steps.py` | 0 | 1 |
| #227 | # Issue #227 — No handling of paginated/async dropdown options (adapters/browser/page_source.py) — FR-PREFILL-3 | `enh_227_async_dropdown_options.feature` | `test_enh_t03_ats_steps.py` | 0 | 1 |
| #228 | Admin gate refuses remote callers in unconfigured mode | `enh_228_require_admin_loopback.feature` | `test_enh_t01_security_steps.py` | 0 | 2 |
| #229 | Engine 5xx detail is masked before reaching the browser | `enh_229_raw_error_leak.feature` | `test_enh_t01_security_steps.py` | 0 | 2 |
| #230 | Engine callback access requires owner attribution | `enh_230_unattributed_callback.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #231 | The feature-state endpoint does not leak engine configuration | `enh_231_features_unauthenticated.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #232 | # Issue #232 — workspace/routes/applicant_email_routes.py + applicant_chat_routes.py | `enh_232_list_campaigns_isinstance_guard.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #233 | A failed digest email send does not permanently consume its dedup key | `enh_233_send_email_dedup_before_dispatch.feature` | `test_enh_t06_notifications_steps.py` | 0 | 2 |
| #234 | One failed channel delivery does not abort the rest of the ladder advance | `enh_234_one_failure_crashes_tick.feature` | `test_enh_t06_notifications_steps.py` | 0 | 1 |
| #235 | The notification delivery state machine is guarded against concurrent access | `enh_235_sent_dict_lock.feature` | `test_enh_t06_notifications_steps.py` | -1 | 2 |
| #236 | The email escalation delay can never be driven to an instant zero-second blast | `enh_236_email_timeout_floor.feature` | `test_enh_t06_notifications_steps.py` | 0 | 2 |
| #237 | Approve and decline signals are recorded but never bias scoring | `enh_237_feature_stats_unread.feature` | `test_enh_t05_learning_steps.py` | 2 | 1 |
| #238 | The converting-role centroid works directly but is never populated by the live loop | `enh_238_record_converting_role_dead.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #239 | Digest score reuse keys on criteria only, ignoring learning state | `enh_239_digest_cache_ignores_learning.feature` | `test_enh_t05_learning_steps.py` | 2 | 1 |
| #240 | A failed conversion never breaks a submission but is lost without a log | `enh_240_conversion_loop_swallows.feature` | `test_enh_t05_learning_steps.py` | 1 | 1 |
| #241 | # Issue #241 — adapters/storage/in_memory.py (commit / rollback) | `enh_241_inmemory_transactional.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #242 | # Issue #242 — adapters/storage/repositories.py AgentRunRepo (latest / max_seq / prune_old) | `enh_242_agentrun_repo_n_plus_one.feature` | `test_enh_t04_orchestration_steps.py` | 2 | 2 |
| #243 | # Issue #243 — adapters/storage/models.py (DiscoverySourceModel, OnboardingProfileModel) | `enh_243_missing_unique_constraints.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 3 |
| #244 | # Issue #244 — adapters/storage/alembic/versions/0001_initial.py vs models.JSONType | `enh_244_json_vs_jsonb_migration.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 2 |
| #245 | # Issue #245 — adapters/storage/models.py (JobPostingModel.normalized, | `enh_245_dead_sql_columns.feature` | `test_enh_t04_orchestration_steps.py` | 1 | 3 |
| #246 | Material generation enforces truthfulness and surfaces silent degradation | `enh_246_silent_failure_diagnostics.feature` | `test_enh_t07_materials_steps.py` | 2 | 1 |
| #247 | Form controls carry associated labels for screen readers | `enh_247_placeholder_as_label.feature` | `test_enh_t08_frontend_steps.py` | 0 | 2 |
| #248 | Loading overlay removal tied to app initialization | `enh_248_loader_timeout_blank_page.feature` | `test_enh_t08_frontend_steps.py` | 0 | 2 |
| #249 | Non-submit buttons declare type=button | `enh_249_buttons_missing_type.feature` | `test_enh_t08_frontend_steps.py` | 0 | 2 |
| #250 | Localization infrastructure for the front-door UI | `enh_250_zero_i18n_infra.feature` | `test_enh_t08_frontend_steps.py` | -1 | 3 |
| #251 | HTML serving is contained to its base directory | `enh_251_serve_html_containment.feature` | `test_enh_t01_security_steps.py` | 0 | 2 |
| #252 | A catch-all exception handler enriches unhandled crashes | `enh_252_generic_exception_handler.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #253 | # Issue #253 — workspace/services/search/ is a dead duplicate of workspace/src/search/ | `enh_253_services_search_dup.feature` | `test_enh_t09_deadcode_steps.py` | 1 | 2 |
| #254 | # Issue #254 — workspace/services/faces/ package is entirely dead | `enh_254_services_faces_dead.feature` | `test_enh_t09_deadcode_steps.py` | 0 | 2 |
| #255 | # Issue #255 — workspace/mcp_servers/_common.py is orphaned | `enh_255_mcp_common_orphan.feature` | `test_enh_t09_deadcode_steps.py` | 0 | 2 |
| #256 | # Issue #256 — Inter woff2 files allegedly never loaded; GohuFont.ttf unreferenced | `enh_256_inter_fonts_unloaded.feature` | `test_enh_t09_deadcode_steps.py` | 0 | 2 |
| #257 | # Issue #257 — workspace/static/js/calendar/reminders.js is orphaned | `enh_257_calendar_reminders_orphan.feature` | `test_enh_t09_deadcode_steps.py` | 1 | 2 |
| #258 | # Issue #258 — Orphan route audit: /api/applicant/email/* — workspace/routes/applicant_email_routes.py | `enh_258_email_route_consumer.feature` | `test_enh_t11_integration_steps.py` | 3 | 0 |
| #259 | # Issue #259 — Orphan route audit: /api/applicant/research/* — workspace/routes/applicant_research_routes.py | `enh_259_research_route_consumer.feature` | `test_enh_t11_integration_steps.py` | 3 | 0 |
| #260 | Email toolbar launcher is reachable for feature gating | `enh_260_missing_tool_email_btn.feature` | `test_enh_t08_frontend_steps.py` | 1 | 1 |
| #261 | # Issue #261 — the frontend/ directory is deprecated but still ships dead weight | `enh_261_frontend_dir_deprecated.feature` | `test_enh_t09_deadcode_steps.py` | 2 | 2 |
| #262 | # Issue #262 — of 7 workspace font files, the stylesheet declares only the 3 FiraCode | `enh_262_workspace_fonts_partial.feature` | `test_enh_t09_deadcode_steps.py` | 1 | 2 |
| #263 | # Issue #263 — five workspace/scripts/ one-shot tools have zero cross-references | `enh_263_oneshot_scripts_orphan.feature` | `test_enh_t09_deadcode_steps.py` | 1 | 2 |
| #264 | # Issue #264 — applicantPortal.js, applicantActivity.js, applicantUpdate.js orphaned | `enh_264_applicant_modules_orphan.feature` | `test_enh_t09_deadcode_steps.py` | 1 | 2 |
| #265 | # Issue #265 — the 1.1MB style.css almost certainly contains substantial dead CSS | `enh_265_style_css_bloat.feature` | `test_enh_t09_deadcode_steps.py` | 0 | 2 |
| #266 | The internal-tool bypass can be disabled | `enh_266_internal_token_disable_flag.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #267 | Owner impersonation requires admin privilege at the auth layer | `enh_267_impersonation_admin_gate.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #268 | The content-security policy does not trust a third-party CDN for scripts | `enh_268_csp_third_party_cdn.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #269 | The session cookie can be marked Secure for TLS deployments | `enh_269_session_cookie_secure.feature` | `test_enh_t01_security_steps.py` | 1 | 2 |
| #270 | # Issue #270 — _fetchJSON/esc/_toast duplicated identically across applicant modules | `enh_270_applicant_boilerplate_dup.feature` | `test_enh_t09_deadcode_steps.py` | 1 | 2 |
| #271 | OOBE wizard step count matches the documented flow | `enh_271_oobe_step_count.feature` | `test_enh_t08_frontend_steps.py` | 1 | 1 |
| #273 | AI-suggested attribute card is fed by engine-surfaced proposals | `enh_273_suggested_attribute_card.feature` | `test_enh_t07_materials_steps.py` | 1 | 1 |
| #274 | Settings tab host divs live in real markup | `enh_274_settings_host_divs.feature` | `test_enh_t08_frontend_steps.py` | 2 | 0 |
| #275 | The live ATS dry-run fails on a browser fault instead of silently passing | `enh_275_dryrun_xfail_in_body.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #276 | The zero-command-line acceptance step asserts something concrete | `enh_276_tautological_bdd_step.feature` | `test_enh_t10_deploy_steps.py` | -1 | 2 |
| #277 | The workspace compile check runs under the project interpreter | `enh_277_compileall_uses_uv.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #278 | CI is not blocked indefinitely when the self-hosted runner is offline | `enh_278_ci_hosted_fallback.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #279 | A rollback reverts the code and images, not only the database | `enh_279_rollback_reverts_code.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #280 | The deploy script does not pass the DB password on the command line | `enh_280_deploy_password_leak.feature` | `test_enh_t01_security_steps.py` | -1 | 2 |
| #281 | The installer surfaces a failed source pull instead of swallowing it | `enh_281_install_pull_failure.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #282 | Database backups are pruned so the disk cannot fill indefinitely | `enh_282_backup_rotation.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #283 | The installer will not regenerate credentials against an initialized database | `enh_283_cred_regen_guard.feature` | `test_enh_t10_deploy_steps.py` | 0 | 1 |
| #284 | # Issue #284 — ensure-submittable test only checks status 200 (app/routers/documents.py) — FR-RESUME-8 | `enh_284_ensure_submittable_body.feature` | `test_enh_t03_ats_steps.py` | 2 | 0 |
| #285 | # Issue #285 — _is_context_error false positives (adapters/llm/openai_compatible.py) — FR-MIND | `enh_285_context_error_false_positive.feature` | `test_enh_t03_ats_steps.py` | 2 | 1 |
| #286 | # Issue #286 — Memory backend default — src/applicant/adapters/memory/factory.py + app/config.py | `enh_286_memory_bridge_default.feature` | `test_enh_t11_integration_steps.py` | 1 | 2 |
| #287 | # Issue #287 — Email surface wiring — workspace/routes/applicant_email_routes.py + emailLibrary/applicantDigest.js | `enh_287_email_surface_wired.feature` | `test_enh_t11_integration_steps.py` | 1 | 2 |
| #288 | # Issue #288 — Calendar integration is read-only — workspace/routes/applicant_internal_routes.py | `enh_288_calendar_read_only.feature` | `test_enh_t11_integration_steps.py` | 1 | 2 |
| #289 | Document library has cross-surface visibility into résumé variant outcomes | `enh_289_doclib_cross_surface.feature` | `test_enh_t07_materials_steps.py` | 1 | 2 |
| #290 | # Issue #290 — Chat-driven campaign control — workspace/routes/applicant_chat_routes.py + chat_tools.py | `enh_290_chat_steering.feature` | `test_enh_t11_integration_steps.py` | 1 | 4 |
| #291 | # Issue #291 — Two-way Applicant email workflow — applicant_email_routes.py + engine notification path | `enh_291_email_two_way.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #292 | # Issue #292 — Calendar write + availability — workspace/routes/applicant_internal_routes.py | `enh_292_calendar_write.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #293 | Applicant materials as first-class documents in the library | `enh_293_doclib_integration.feature` | `test_enh_t07_materials_steps.py` | 1 | 2 |
| #294 | # Issue #294 — Memory bridge as default + two-way learning — factory.py + app/config.py | `enh_294_memory_two_way_learning.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #295 | # Issue #295 — Tasks integration — pending actions as first-class workspace tasks | `enh_295_tasks_integration.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #296 | # Issue #296 — Gallery integration — Applicant screenshots/materials as gallery collections | `enh_296_gallery_integration.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #297 | # Issue #297 — Wire up the Compare surface — cross-entity comparison backend | `enh_297_compare_wiring.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #298 | # Issue #298 — Local LLM tier delegation — src/applicant/adapters/llm/openai_compatible.py | `enh_298_local_llm_tier_delegation.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #299 | # Issue #299 — Research integration — company/role deep research before applications | `enh_299_research_integration.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #300 | Urgent action alerts are pushed to the user's device via the ntfy channel | `enh_300_ntfy_push.feature` | `test_enh_t06_notifications_steps.py` | -1 | 3 |
| #301 | # Issue #301 — Unified settings surface — workspace/static/js/settings.js | `enh_301_settings_surface.feature` | `test_enh_t11_integration_steps.py` | 1 | 2 |
| #302 | Time-based quiet-hours suppression with per-channel and override controls | `enh_302_quiet_hours_suppression.feature` | `test_enh_t06_notifications_steps.py` | 1 | 3 |
| #303 | # Issue #303 — Remove: Notes integration with Applicant (explicitly descoped) | `enh_303_remove_notes_integration.feature` | `test_enh_t11_integration_steps.py` | 3 | 0 |
| #304 | # Issue #304 — Remove: Cookbook integration with Applicant (descoped, except local-LLM tier) | `enh_304_remove_cookbook_integration.feature` | `test_enh_t11_integration_steps.py` | 0 | 3 |
| #305 | Plan-as-data execution — typed-DSL planner over a semantic DOM | `enh_305_plan_as_data.feature` | `test_enh_research_steps.py` | -1 | 6 |
| #306 | Self-improvement learning flywheel — induce, curate, reflect | `enh_306_learning_flywheel.feature` | `test_enh_research_steps.py` | -1 | 5 |
| #307 | Vendor-able agent-memory backend behind the memory port | `enh_307_memory_backend.feature` | `test_enh_research_steps.py` | -1 | 4 |
| #308 | Expose the engine as an MCP server | `enh_308_mcp_server.feature` | `test_enh_research_steps.py` | -1 | 3 |
| #309 | Browser-agent eval harness for the pre-fill planner | `enh_309_eval_harness.feature` | `test_enh_research_steps.py` | -1 | 4 |
| #310 | SSRF guard covers the entry URL and every redirect / subresource hop | `enh_310_ssrf_redirect.feature` | `test_enh_research_steps.py` | 1 | 3 |
| #311 | Privilege gate defaults to deny for unknown keys | `enh_311_require_privilege.feature` | `test_enh_research_steps.py` | 0 | 2 |
| #312 | Engine warns when it falls back to in-memory storage at boot | `enh_312_db_fallback_warning.feature` | `test_enh_research_steps.py` | 0 | 2 |
| #313 | The app_api LLM tool MUST gate reachable endpoints with an explicit | `enh_313_app_api_allowlist.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #314 | The vault_get tool MUST mask passwords and TOTP secrets from the | `enh_314_vault_get_masking.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #315 | When the model creates an API token, the tool MUST NOT place the raw | `enh_315_manage_tokens_masking.feature` | `test_enh_n1_security_steps.py` | 0 | 1 |
| #316 | On shutdown the engine MUST drain/stop the scheduler loop AND flush | `enh_316_graceful_shutdown.feature` | `test_enh_n5_lifecycle_steps.py` | 1 | 2 |
| #317 | The chat proxy MUST pass the engine's reply through a scrubber that | `enh_317_chat_scrub.feature` | `test_enh_n1_security_steps.py` | 0 | 1 |
| #318 | The onboarding save-section endpoint MUST reject structurally invalid | `enh_318_typed_intake.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #319 | The add-endpoint route MUST validate its inputs with a typed model — | `enh_319_endpoint_form_model.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #320 | Resource-id path parameters MUST be format-validated (non-empty, | `enh_320_path_param_validation.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #322 | Every file-upload endpoint MUST enforce a maximum body size and reject | `enh_322_upload_size_limit.feature` | `test_enh_n1_security_steps.py` | 2 | 1 |
| #323 | The front-door MUST emit a diagnostic (a logger warning) when an IMAP | `enh_323_builtin_actions_silent_imap.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #324 | The front-door agent loop MUST emit a diagnostic (a logger warning) when | `enh_324_agent_loop_silent_prefs.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #325 | The front-door MUST emit a diagnostic (a logger warning) when a memory | `enh_325_ai_interaction_silent_vector.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #326 | The front-door background-job loader MUST emit a diagnostic (a logger | `enh_326_bg_jobs_corrupt_state.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #327 | The front-door chat MUST wrap every JSON.parse of an SSE stream chunk | `enh_327_chat_json_parse_guard.feature` | `test_enh_n3_wsjs_steps.py` | 2 | 1 |
| #328 | When a note archive/unarchive/delete/edit API call fails, the front-door | `enh_328_notes_mutation_feedback.feature` | `test_enh_n3_wsjs_steps.py` | 1 | 1 |
| #329 | When the email inbox lazily imports ./ui.js to show a toast/error and that | `enh_329_emailinbox_import_feedback.feature` | `test_enh_n3_wsjs_steps.py` | 1 | 2 |
| #330 | When the assistant lazily imports ./applicantChat.js and that import | `enh_330_assistant_chat_import_feedback.feature` | `test_enh_n3_wsjs_steps.py` | 1 | 1 |
| #331 | The document module's open/minimize-state localStorage writes MUST be | `enh_331_document_storage_guard.feature` | `test_enh_n3_wsjs_steps.py` | 1 | 1 |
| #332 | Every bare `except Exception:` block in the workspace route files MUST emit | `enh_332_routes_silent_excepts_umbrella.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #333 | Every bare `except Exception:` block in the workspace source files MUST emit | `enh_333_source_silent_excepts_umbrella.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #334 | Workspace front-end modules MUST NOT swallow errors in empty catch | `enh_334_workspace_js_silent_catches.feature` | `test_enh_n3_wsjs_steps.py` | 1 | 2 |
| #335 | The engine's `_safe_teardown()` MUST emit a diagnostic (a logger warning) | `enh_335_page_source_teardown_silent.feature` | `test_enh_n2_silenterr_steps.py` | 0 | 2 |
| #336 | The engine MUST catch browser-disconnection failures (TimeoutError / | `enh_336_browser_crash_recovery.feature` | `test_enh_n4_browser_steps.py` | 1 | 2 |
| #337 | The in-memory FakePageSource MUST approximate PlaywrightPageSource's | `enh_337_fake_page_source_parity.feature` | `test_enh_n4_browser_steps.py` | 2 | 4 |
| #338 | The Chrome launch args MUST NOT pass --enable-unsafe-swiftshader to a | `enh_338_swiftshader_flag_version_gate.feature` | `test_enh_n4_browser_steps.py` | 1 | 1 |
| #339 | _on_response MUST capture a timestamp alongside the response status so the | `enh_339_on_response_timestamp.feature` | `test_enh_n4_browser_steps.py` | 0 | 1 |
| #340 | detect_chrome_major MUST also probe chromium, chromium-browser, and | `enh_340_chrome_probe_container_paths.feature` | `test_enh_n4_browser_steps.py` | 1 | 1 |
| #341 | advance()'s end-of-flow detection MUST re-check for a DOM change after a | `enh_341_spa_hydration_race.feature` | `test_enh_n4_browser_steps.py` | 0 | 1 |
| #342 | The dropdown filter cleanup MUST check whether the page navigated after | `enh_342_dropdown_cleanup_detached.feature` | `test_enh_n4_browser_steps.py` | 0 | 1 |
| #343 | _filter_query MUST type enough of a long, multi-word value (more than the | `enh_343_filter_query_shared_prefix.feature` | `test_enh_n4_browser_steps.py` | 1 | 1 |
| #344 | With no search criteria set a posting MUST score the documented neutral | `enh_344_cold_start_viability_gate.feature` | `test_enh_n5_lifecycle_steps.py` | 2 | 1 |
| #345 | When the model returns JSON that parses but lacks a "score" key, the | `enh_345_loose_json_no_score_log.feature` | `test_enh_n5_lifecycle_steps.py` | 2 | 1 |
| #346 | The CORS allowed-origins parser MUST strip surrounding whitespace | `enh_346_cors_origins_parse.feature` | `test_enh_n1_security_steps.py` | 0 | 1 |
| #347 | .env.example MUST document SECURE_COOKIES, MAX_UPLOAD_SIZE, | `enh_347_env_example_missing_docs.feature` | `test_enh_n5_lifecycle_steps.py` | 1 | 3 |
| #348 | The project MUST either widen requires-python to admit Python 3.12 | `enh_348_python_version_pin.feature` | `test_enh_n5_lifecycle_steps.py` | 1 | 1 |
| #349 | The static alembic.ini sqlalchemy.url MUST be an obviously-fake | `enh_349_alembic_placeholder.feature` | `test_enh_n1_security_steps.py` | 0 | 1 |
| #350 | CaptchaSolverPort — opt-in, safe-by-default CAPTCHA handling | `enh_350_captcha_solver_port.feature` | `test_enh_skyvern_steps.py` | 1 | 6 |
| #351 | Skyvern parity — autonomous form-filling capability bridge | `enh_351_skyvern_parity.feature` | `test_enh_skyvern_steps.py` | -1 | 5 |
| #352 | The Cookbook running view drives remote command execution | `enh_352_cookbook_shell_safety.feature` | `test_enh_n3_wsjs_steps.py` | 1 | 2 |
| #353 | The research panel MUST HTML-escape every scraped/LLM-derived string it | `enh_353_research_html_sanitize.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #354 | All LLM/agent output rendered into the chat DOM MUST be sanitized so | `enh_354_chat_render_xss.feature` | `test_enh_n1_security_steps.py` | 2 | 1 |
| #355 | The engine and workspace container images MUST build on the same Python | `enh_355_dockerfile_python_mismatch.feature` | `test_enh_n5_lifecycle_steps.py` | 1 | 1 |
| #356 | The webhook_token column MUST NOT persist a plaintext token — it is | `enh_356_webhook_token_encryption.feature` | `test_enh_n1_security_steps.py` | 1 | 1 |
| #357 | The editor JS surface MUST be individually audited — at minimum the | `enh_357_editor_js_audit_tracking.feature` | `test_enh_n5_lifecycle_steps.py` | 2 | 1 |
| #358 | Every remaining unaudited area listed in this master tracker MUST be | `enh_358_master_audit_tracking.feature` | `test_enh_n5_lifecycle_steps.py` | 2 | 1 |
| #360 | The engine MUST scan/neutralize untrusted scraped text (job description, | `enh_360_prompt_injection_scoring.feature` | `test_enh_systemic_steps.py` | 0 | 4 |
| #361 | The vault MUST support master-key rotation (re-encrypt all stored secrets | `enh_361_vault_key_rotation.feature` | `test_enh_systemic_steps.py` | -1 | 3 |
| #362 | The engine MUST emit operational metrics (tick success/failure, scheduler | `enh_362_loop_metrics_alerting.feature` | `test_enh_systemic_steps.py` | 0 | 3 |
| #363 | Deleting a campaign (or user) MUST purge all associated résumés, parsed PII, | `enh_363_pii_erasure_retention.feature` | `test_enh_systemic_steps.py` | 1 | 3 |
| #364 | A runnable end-to-end test MUST exercise the full pipeline (discovery → | `enh_364_e2e_pipeline_harness.feature` | `test_enh_systemic_steps.py` | 1 | 2 |
| #365 | A test MUST stand up a database at a prior revision with representative rows, | `enh_365_migration_data_integrity.feature` | `test_enh_systemic_steps.py` | 0 | 2 |
| #366 | The front-door MUST have a JS unit-test harness (a configured test runner | `enh_366_js_test_harness.feature` | `test_enh_systemic_steps.py` | -1 | 3 |
| #367 | Before pre-fill/apply, the engine MUST score a posting for scam / | `enh_367_scam_ghost_job_guard.feature` | `test_enh_spirit_steps.py` | -1 | 3 |
| #368 | Before applying, the engine MUST check the user's own application | `enh_368_reapply_cooldown_guard.feature` | `test_enh_spirit_steps.py` | 1 | 2 |
| #369 | Scoring/discovery MUST down-rank or exclude postings whose stated | `enh_369_work_auth_eligibility_filter.feature` | `test_enh_spirit_steps.py` | 2 | 2 |
| #370 | After rendering, the engine MUST run an ATS-parseability self-check on | `enh_370_ats_parseability_selfcheck.feature` | `test_enh_spirit_steps.py` | 1 | 2 |
| #371 | The engine MUST enforce a configurable per-company application cap per | `enh_371_per_company_volume_cap.feature` | `test_enh_spirit_steps.py` | 1 | 2 |
| #372 | On submission (or review-approval at the stop-boundary), the engine | `enh_372_submission_snapshot.feature` | `test_enh_spirit_steps.py` | 1 | 2 |
