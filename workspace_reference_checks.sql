-- Deferred checks preserve batch/regrouping order without trusting JSON ownership.
CREATE FUNCTION teacher_ai_check_reference(w uuid, kind text, target text)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE present boolean;
BEGIN
  IF target IS NULL OR target='' THEN RETURN; END IF;
  CASE kind
    WHEN 'monthly' THEN SELECT EXISTS(SELECT 1 FROM public.monthly_plans WHERE workspace_id=w AND id=target) INTO present;
    WHEN 'item' THEN SELECT EXISTS(SELECT 1 FROM public.monthly_learning_items WHERE workspace_id=w AND id=target) INTO present;
    WHEN 'carry' THEN SELECT EXISTS(SELECT 1 FROM public.carryover_items WHERE workspace_id=w AND id=target) INTO present;
    WHEN 'review' THEN SELECT EXISTS(SELECT 1 FROM public.period_reviews WHERE workspace_id=w AND period_id=target) INTO present;
    WHEN 'progress' THEN SELECT EXISTS(SELECT 1 FROM public.actual_progress WHERE workspace_id=w AND id::text=target) INTO present;
    ELSE RAISE EXCEPTION 'Invalid relationship category';
  END CASE;
  IF NOT present THEN RAISE EXCEPTION 'Workspace relationship is unavailable' USING ERRCODE='23503'; END IF;
END $$;

CREATE FUNCTION teacher_ai_check_json_references() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE packet jsonb; lesson jsonb; link jsonb; field text; target jsonb;
BEGIN
  CASE TG_TABLE_NAME
    WHEN 'monthly_learning_items' THEN
      packet=NEW.item_data::jsonb;
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'monthly',packet->>'monthly_plan_id');
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',packet->>'split_from');
      FOR target IN SELECT value FROM jsonb_array_elements(COALESCE(packet->'merged_from','[]'::jsonb)) LOOP
        PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',target#>>'{}');
      END LOOP;
      FOR target IN SELECT value FROM jsonb_array_elements(COALESCE(packet->'replacement_from','[]'::jsonb)) LOOP
        PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',target#>>'{}');
      END LOOP;
    WHEN 'monthly_item_updates' THEN
      packet=NEW.update_data::jsonb;
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',packet->>'item_id');
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'progress',packet->>'record_id');
    WHEN 'carryover_items' THEN
      packet=NEW.item_data::jsonb;
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'review',packet->>'period_id');
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',packet->>'monthly_item_id');
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',packet->>'previous_monthly_item_id');
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',packet->>'duplicate_of_monthly_item_id');
      FOR target IN SELECT value FROM jsonb_array_elements(COALESCE(packet->'candidate_monthly_item_ids','[]'::jsonb)) LOOP
        PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',target#>>'{}');
      END LOOP;
    WHEN 'period_reviews' THEN
      packet=NEW.review_data::jsonb;
      IF packet->>'period_id' IS DISTINCT FROM NEW.period_id THEN RAISE EXCEPTION 'Invalid period identifier'; END IF;
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'monthly',packet->'monthly_plan'->>'id');
    WHEN 'day_plans' THEN packet=NEW.plan_data::jsonb;
    WHEN 'lesson_progress' THEN packet=NEW.lesson_data::jsonb;
    WHEN 'lesson_resources' THEN
      packet=NEW.resource_data::jsonb;
      IF packet->>'id' IS DISTINCT FROM NEW.id OR packet->>'plan_id' IS DISTINCT FROM NEW.plan_id
        OR packet->>'lesson_id' IS DISTINCT FROM NEW.lesson_id
        OR packet->>'planning_date' IS DISTINCT FROM NEW.planning_date THEN
        RAISE EXCEPTION 'Invalid resource parent';
      END IF;
      -- Historical lesson snapshots remain valid independently of current plans.
      packet=jsonb_build_object('lessons',jsonb_build_array(packet->'lesson_snapshot'));
    ELSE RETURN NEW;
  END CASE;
  IF packet ? 'workspace_id' OR packet ? 'user_id' THEN RAISE EXCEPTION 'JSON cannot choose workspace ownership'; END IF;
  IF TG_TABLE_NAME='monthly_learning_items' THEN
    IF packet->>'id' IS DISTINCT FROM NEW.id THEN RAISE EXCEPTION 'Invalid learning identifier'; END IF;
  END IF;
  PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'monthly',packet->'monthly_plan'->>'id');
  FOR lesson IN SELECT value FROM jsonb_array_elements(COALESCE(packet->'lessons','[]'::jsonb)) LOOP
    FOR link IN SELECT value FROM jsonb_array_elements(COALESCE(lesson->'monthly_item_links','[]'::jsonb)) LOOP
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',link->>'item_id');
    END LOOP;
    FOR link IN SELECT value FROM jsonb_array_elements(COALESCE(lesson->'item_updates','[]'::jsonb)) LOOP
      PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'item',link->>'item_id');
    END LOOP;
    FOREACH field IN ARRAY ARRAY['carryover_ids','completed_carryover_ids'] LOOP
      FOR target IN SELECT value FROM jsonb_array_elements(COALESCE(lesson->field,'[]'::jsonb)) LOOP
        PERFORM public.teacher_ai_check_reference(NEW.workspace_id,'carry',target#>>'{}');
      END LOOP;
    END LOOP;
  END LOOP;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION teacher_ai_check_reference(uuid,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION teacher_ai_check_json_references() FROM PUBLIC;
