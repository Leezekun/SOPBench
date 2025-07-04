cd ../..

model="gpt-4o-mini"
domains=("bank" "healthcare" "university" "dmv" "online_market" "hotel" "library")
method="fc"

# Experiment 1: full and oracle tool list
tool_lists=("full" "oracle")
for domain in "${domains[@]}"; do
    for tool_list in "${tool_lists[@]}"; do
        CUDA_VISIBLE_DEVICES=$devices python run_simulation.py \
                --domain $domain \
                --assistant_model $model \
                --env_mode prompt \
                --tool_list $tool_list \
                --tool_call_mode $method \
                --num_run_per_interaction 3
    done
done

# Experiment 2: Adversarial User Attack
method="fc"
domains=("healthcare")
tool_list="full"
for domain in "${domains[@]}"; do
    CUDA_VISIBLE_DEVICES=$devices python run_simulation.py \
            --domain $domain \
            --user_model adv \
            --assistant_model $model \
            --env_mode prompt \
            --tool_list $tool_list \
            --tool_call_mode $method
done