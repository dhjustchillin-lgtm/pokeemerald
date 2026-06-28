ProfOlive_EventScript_UpdateLocation::
	goto_if_eq VAR_PETALBURG_GYM_STATE, 0, Common_EventScript_NopReturn
	goto_if_set FLAG_SYS_GAME_CLEAR, ProfOlive_EventScript_MoveToLab
	call_if_eq VAR_OLIVE_STATE, 0, ProfOlive_EventScript_MoveToLab
	call_if_eq VAR_OLIVE_STATE, 1, ProfOlive_EventScript_MoveToLab
	call_if_eq VAR_OLIVE_STATE, 2, ProfOlive_EventScript_MoveToRoute101
	call_if_eq VAR_OLIVE_STATE, 3, ProfOlive_EventScript_MoveToRoute101
	call_if_eq VAR_OLIVE_STATE, 4, ProfOlive_EventScript_MoveToRoute103
	call_if_eq VAR_OLIVE_STATE, 5, ProfOlive_EventScript_MoveToRoute103
	call_if_eq VAR_OLIVE_STATE, 6, ProfOlive_EventScript_MoveToLab
	call_if_eq VAR_OLIVE_STATE, 7, ProfOlive_EventScript_MoveToLab
	return

ProfOlive_EventScript_MoveToLab::
	clearflag FLAG_HIDE_LITTLEROOT_TOWN_OLIVES_LAB_OLIVE
	clearflag FLAG_HIDE_LITTLEROOT_TOWN_OLIVES_LAB_UNKNOWN_0x380
	setflag FLAG_HIDE_ROUTE_101_OLIVE
	setflag FLAG_HIDE_ROUTE_103_OLIVE
	return

ProfOlive_EventScript_MoveToRoute101::
	clearflag FLAG_HIDE_ROUTE_101_OLIVE
	setflag FLAG_HIDE_LITTLEROOT_TOWN_OLIVES_LAB_OLIVE
	setflag FLAG_HIDE_LITTLEROOT_TOWN_OLIVES_LAB_UNKNOWN_0x380
	setflag FLAG_HIDE_ROUTE_103_OLIVE
	return

ProfOlive_EventScript_MoveToRoute103::
	clearflag FLAG_HIDE_ROUTE_103_OLIVE
	setflag FLAG_HIDE_ROUTE_101_OLIVE
	setflag FLAG_HIDE_LITTLEROOT_TOWN_OLIVES_LAB_OLIVE
	setflag FLAG_HIDE_LITTLEROOT_TOWN_OLIVES_LAB_UNKNOWN_0x380
	return

ProfOlive_EventScript_RatePokedexOrRegister::
	lock
	faceplayer
	goto_if_unset FLAG_HAS_MATCH_CALL, ProfOlive_EventScript_AskRatePokedex
	goto_if_unset FLAG_ENABLE_PROF_OLIVE_MATCH_CALL, EventScript_RegisterProfOlive

ProfOlive_EventScript_AskRatePokedex::
	msgbox gOliveDexRatingText_AreYouCurious, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, NO, ProfOlive_EventScript_DeclineRating
	call ProfOlive_EventScript_RatePokedex
	release
	end

ProfOlive_EventScript_DeclineRating::
	msgbox gOliveDexRatingText_Cancel, MSGBOX_DEFAULT
	release
	end

ProfOlive_EventScript_ShowRatingMessage::
	copyvar VAR_0x8004, VAR_0x8009
	special ShowPokedexRatingMessage
	waitmessage
	waitbuttonpress
	return

ProfOlive_EventScript_RatePokedex::
	setvar VAR_0x8004, 0
	specialvar VAR_RESULT, ScriptGetPokedexInfo
	copyvar VAR_0x8008, VAR_0x8005
	copyvar VAR_0x8009, VAR_0x8006
	copyvar VAR_0x800A, VAR_RESULT
	buffernumberstring STR_VAR_1, VAR_0x8008  @ Num Hoenn seen
	buffernumberstring STR_VAR_2, VAR_0x8009  @ Num Hoenn caught
	msgbox gOliveDexRatingText_SoYouveSeenAndCaught, MSGBOX_DEFAULT
	call ProfOlive_EventScript_ShowRatingMessage
	goto_if_eq VAR_0x800A, 0, Common_EventScript_NopReturn  @ National dex not enabled
	setvar VAR_0x8004, 1
	specialvar VAR_RESULT, ScriptGetPokedexInfo
	copyvar VAR_0x8008, VAR_0x8005
	copyvar VAR_0x8009, VAR_0x8006
	buffernumberstring STR_VAR_1, VAR_0x8008  @ Num National seen
	buffernumberstring STR_VAR_2, VAR_0x8009  @ Num National caught
	msgbox gOliveDexRatingText_OnANationwideBasis, MSGBOX_DEFAULT
	return
